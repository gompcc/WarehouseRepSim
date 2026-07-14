"""ETA-based station reservations.

Baseline station scoring looks at fill *now*: it counts carts currently on
(or reserved onto) station tiles. That is reactive — a station "full" now may
have every occupant finishing its picks before our cart could even get there,
while an "empty" station may already have three carts in transit toward it.

This module scores stations by **predicted occupancy at the cart's arrival
time (ETA)**:

- ETA = AGV fetch time + pickup + true *directed* travel time (one-way loop
  distances from :class:`DistanceMap`, not Manhattan) + dropoff.
- Occupants that will finish picking and be hauled away before ETA are
  subtracted; carts already routed there (job reservations) are added.

It also publishes a fixed-horizon forecast per station for the GUI overlay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..enums import AGVState, JobType, TileType
from ..constants import PICKUP_TIME, DROPOFF_TIME, TILE_TRAVEL_TIME
from ..models import STATIONS
from .distances import DistanceMap, INF

if TYPE_CHECKING:
    from ..agv import AGV
    from ..models import Cart

# Cost weight: how many seconds of extra travel we accept to reach a station
# that is one whole capacity-fraction emptier at arrival. Calibrated to match
# the baseline's fill/distance balance (lessons.md iteration 11: weight 45
# already over-chases empty stations; 30 is near-optimal).
FILL_WEIGHT = 30.0
# Estimated seconds between "picks complete" and the station tile being
# physically freed (AGV response + pickup handling).
DEPART_OVERHEAD = 30.0
# Fallback AGV fetch estimate when no idle AGV exists right now.
DEFAULT_FETCH_SECONDS = 20.0
# Horizon used for the per-station GUI forecast display.
DISPLAY_HORIZON = 60.0


class ETAReservations:
    """Predictive station selector (toggle: ``eta_reservations``)."""

    def __init__(self, dist_map: DistanceMap) -> None:
        self.dist_map = dist_map

    # ------------------------------------------------------------------
    # Prediction model
    # ------------------------------------------------------------------

    def predicted_occupancy(
        self,
        dispatcher,
        station_id: str,
        eta: float,
        carts: list[Cart],
        exclude_cart: Cart | None = None,
    ) -> float:
        """Predicted number of occupied tiles at *station_id* in *eta* seconds."""
        station_tiles = set(
            dispatcher._station_tiles.get((station_id, TileType.PICK_STATION), [])
        )
        count = 0.0
        for cart in carts:
            if cart is exclude_cart or cart.carried_by is not None:
                continue
            if cart.pos not in station_tiles:
                continue
            # Occupant stays until picks finish plus haul-away overhead.
            if max(cart.process_timer, 0.0) + DEPART_OVERHEAD > eta:
                count += 1.0
        # Carts already routed here hold a reservation for our arrival window.
        for job in dispatcher.pending_jobs + dispatcher.active_jobs:
            if (
                job.job_type == JobType.MOVE_TO_PICK
                and job.station_id == station_id
                and job.cart is not exclude_cart
            ):
                count += 1.0
        return count

    def _fetch_seconds(self, cart: Cart, agvs: list[AGV]) -> float:
        """Estimate how long an AGV needs to reach *cart* for pickup."""
        best = INF
        for agv in agvs:
            if (
                agv.state == AGVState.IDLE
                and agv.current_job is None
                and agv.carrying_cart is None
            ):
                d = abs(agv.pos[0] - cart.pos[0]) + abs(agv.pos[1] - cart.pos[1])
                best = min(best, d * TILE_TRAVEL_TIME)
        return best if best != INF else DEFAULT_FETCH_SECONDS

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def choose_station(
        self,
        dispatcher,
        cart: Cart,
        candidates: list[int],
        carts: list[Cart],
        agvs: list[AGV],
    ) -> int | None:
        """Pick the best station among *candidates* by ETA-predicted fill.

        Only stations with a currently free (unreserved) tile are eligible —
        the tile-reservation system still needs a concrete target. Among
        those, predicted occupancy at arrival replaces current fill.
        """
        fetch = self._fetch_seconds(cart, agvs)
        scored: list[tuple[float, int]] = []
        overflow: list[tuple[float, int]] = []  # predicted-full fallbacks
        for s in candidates:
            sid = f"S{s}"
            if dispatcher._find_tile(sid, TileType.PICK_STATION, carts) is None:
                continue  # no tile to reserve right now
            travel = self.dist_map.seconds_to_station(cart.pos, sid)
            if travel == INF:
                continue
            eta = fetch + PICKUP_TIME + travel + DROPOFF_TIME
            capacity = STATIONS.get(sid, 0)
            if capacity <= 0:
                continue
            predicted = self.predicted_occupancy(
                dispatcher, sid, eta, carts, exclude_cart=cart,
            )
            score = (predicted / capacity) * FILL_WEIGHT + travel
            if predicted >= capacity:
                overflow.append((score, s))
            else:
                scored.append((score, s))
        pool = scored or overflow
        if not pool:
            return None
        pool.sort()
        return pool[0][1]

    # ------------------------------------------------------------------
    # GUI forecast
    # ------------------------------------------------------------------

    def forecast(
        self, dispatcher, carts: list[Cart], horizon: float = DISPLAY_HORIZON,
    ) -> dict[str, tuple[float, int]]:
        """``{station_id: (predicted_occupancy, capacity)}`` at *horizon* s."""
        result: dict[str, tuple[float, int]] = {}
        for i in range(1, 10):
            sid = f"S{i}"
            predicted = self.predicted_occupancy(dispatcher, sid, horizon, carts)
            result[sid] = (predicted, STATIONS.get(sid, 0))
        return result
