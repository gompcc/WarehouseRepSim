"""Shadow-mode pickers: per-station humans who walk the product aisles.

PRD §14.9. This subsystem is deliberately **independent of the dispatcher**:
pickers *react* to carts sitting at pick stations in ``PICKING`` state, walk
their (sampled) picks in the aisles, and record statistics — but they do not
yet gate cart departure. The cart still leaves on the dispatcher's timer.
Pulling the two together later is a single seam: make the dispatcher's
PICKING branch wait for ``PickerManager.cart_done(cart)`` instead of
``process_timer`` (and derive real pick lists from SKU-based orders).

Workload model (until orders carry real SKUs): when a cart arrives at a
station, the picker crew samples ``max(1, round(N(4, 2)))`` distinct SKUs
uniformly from that station's zoned SKUs — matching the target of ~4 picks
per cart-visit (σ 2). Walking time per pick follows the calibrated aisle
geometry (μ 30 s, σ 10 s round trip; see ``aisles.WALK_TIME_*``), plus
``PICK_GRAB_TIME`` at the slot. A picker carries one SKU line per trip.

Pickers use their own RNG stream so they never perturb the seeded order
stream used by the dispatch-strategy experiments.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from .enums import CartState, TileType
from .constants import PICK_GRAB_TIME, PICKERS_PER_STATION
from .aisles import get_catalog, walk_time_seconds

if TYPE_CHECKING:
    from .models import Cart, Tile

# Target workload per cart-visit at a station (sampled in shadow mode,
# later derived from real SKU orders): mean 4 picks, sd 2, min 1.
PICKS_PER_VISIT_MEAN = 4.0
PICKS_PER_VISIT_SD = 2.0

_PICKER_RNG_SEED = 20260714  # own stream — never touches the global RNG


class Picker:
    """One human picker: walks cart → slot → cart, one SKU line per trip."""

    IDLE = "idle"
    WALK_OUT = "walk_out"
    GRAB = "grab"
    WALK_BACK = "walk_back"

    _next_id = 1

    def __init__(self, station_id: str, home: tuple[float, float]) -> None:
        self.picker_id = Picker._next_id
        Picker._next_id += 1
        self.station_id = station_id
        self.home = home
        self.pos: tuple[float, float] = home
        self.state = Picker.IDLE
        self.cart: Cart | None = None
        self.pending_skus: list[int] = []
        self.current_sku: int | None = None
        self.path: list[tuple[float, float]] = []
        self.leg_time = 0.0  # duration of current walking leg (s)
        self.timer = 0.0     # elapsed in current state (s)

    # -- lifecycle -----------------------------------------------------

    def start_cart(self, cart: Cart, skus: list[int]) -> None:
        self.cart = cart
        self.pending_skus = list(skus)
        self._next_pick()

    def _next_pick(self) -> None:
        if not self.pending_skus:
            self.cart = None
            self.current_sku = None
            self.state = Picker.IDLE
            self.pos = self.home
            return
        self.current_sku = self.pending_skus.pop(0)
        cat = get_catalog()
        self.path = cat.walk_path(self.station_id, self.current_sku)
        one_way = cat.walk_distance(self.station_id, self.current_sku)
        # Half the calibrated round-trip walking time per leg
        self.leg_time = walk_time_seconds(one_way) / 2.0
        self.timer = 0.0
        self.state = Picker.WALK_OUT

    def abort(self) -> None:
        """Cart left early — drop remaining picks and head home."""
        self.pending_skus = []
        if self.state == Picker.WALK_OUT:
            # Walk back the way we came, taking as long as we walked out
            self.leg_time = max(self.timer, 0.1)
            self.timer = 0.0
            self.state = Picker.WALK_BACK
            self.path = list(reversed(self.path))
        elif self.state == Picker.GRAB:
            self.timer = 0.0
            self.state = Picker.WALK_BACK
            self.path = list(reversed(self.path))
        self.cart = None
        self.current_sku = None

    def update(self, dt: float) -> tuple[int, float] | None:
        """Advance the picker. Returns ``(sku, walk_seconds)`` when a pick
        completes (picker back at the cart), else ``None``."""
        if self.state == Picker.IDLE:
            return None
        self.timer += dt

        if self.state == Picker.WALK_OUT and self.timer >= self.leg_time:
            self.timer = 0.0
            self.state = Picker.GRAB
            self.pos = self.path[-1]
        elif self.state == Picker.GRAB and self.timer >= PICK_GRAB_TIME:
            self.timer = 0.0
            self.state = Picker.WALK_BACK
            self.path = list(reversed(self.path))
        elif self.state == Picker.WALK_BACK and self.timer >= self.leg_time:
            done_sku = self.current_sku
            walk_secs = self.leg_time * 2.0
            self.pos = self.home
            if done_sku is not None and self.cart is not None:
                self._next_pick()
                return (done_sku, walk_secs)
            # Was an abort walk-home
            self.state = Picker.IDLE
            self.current_sku = None
            return None

        if self.state in (Picker.WALK_OUT, Picker.WALK_BACK):
            frac = min(1.0, self.timer / self.leg_time) if self.leg_time > 0 else 1.0
            self.pos = _along_path(self.path, frac)
        return None


def _along_path(
    path: list[tuple[float, float]], frac: float,
) -> tuple[float, float]:
    """Point at *frac* (0..1) of the polyline's length."""
    segs = list(zip(path, path[1:]))
    lengths = [abs(x2 - x1) + abs(y2 - y1) for (x1, y1), (x2, y2) in segs]
    total = sum(lengths) or 1.0
    target = frac * total
    run = 0.0
    for ((x1, y1), (x2, y2)), seg_len in zip(segs, lengths):
        if run + seg_len >= target and seg_len > 0:
            t = (target - run) / seg_len
            return (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
        run += seg_len
    return path[-1]


class PickerManager:
    """Runs every station's picker crew; shadow-observes carts in PICKING."""

    def __init__(self, tiles: dict[tuple[int, int], Tile]) -> None:
        cat = get_catalog()
        self.rng = random.Random(_PICKER_RNG_SEED)
        self.station_of_pos: dict[tuple[int, int], str] = {
            pos: t.station_id
            for pos, t in tiles.items()
            if t.tile_type == TileType.PICK_STATION and t.station_id
        }
        self.pickers: dict[str, list[Picker]] = {
            sid: [Picker(sid, cat.station_pos[sid]) for _ in range(PICKERS_PER_STATION)]
            for sid in cat.station_pos
        }
        # Carts waiting for a picker, FIFO per station: [(cart, skus)]
        self.queues: dict[str, list[tuple[Cart, list[int]]]] = {
            sid: [] for sid in cat.station_pos
        }
        self._tracked: set[int] = set()  # cart_ids currently queued or served

        # Stats
        self.picks_done = 0
        self.carts_served = 0
        self.carts_left_early = 0
        self.walk_seconds_total = 0.0
        self.busy_seconds = 0.0
        self.elapsed = 0.0
        self._walk_sum_sq = 0.0  # for running sd of walk time per pick

    # -- workload sampling ----------------------------------------------

    def _sample_picks(self, station_id: str) -> list[int]:
        cat = get_catalog()
        zone = cat.station_skus.get(station_id, [])
        if not zone:
            return []
        n = max(1, round(self.rng.gauss(PICKS_PER_VISIT_MEAN, PICKS_PER_VISIT_SD)))
        return self.rng.sample(zone, min(n, len(zone)))

    # -- main tick -------------------------------------------------------

    def update(self, dt: float, carts: list[Cart]) -> None:
        self.elapsed += dt
        picking_by_id: dict[int, Cart] = {
            c.cart_id: c
            for c in carts
            if c.state == CartState.PICKING and c.carried_by is None
        }

        # 1. New arrivals → sample their picks, queue them
        for cart in picking_by_id.values():
            if cart.cart_id in self._tracked:
                continue
            sid = self.station_of_pos.get(cart.pos)
            if sid is None:
                continue
            self._tracked.add(cart.cart_id)
            self.queues[sid].append((cart, self._sample_picks(sid)))

        # 2. Departures (cart left PICKING while queued or being served)
        for sid, queue in self.queues.items():
            for cart, _skus in list(queue):
                if cart.cart_id not in picking_by_id:
                    queue.remove((cart, _skus))
                    self._tracked.discard(cart.cart_id)
                    self.carts_left_early += 1
        for sid, crew in self.pickers.items():
            for picker in crew:
                if picker.cart is not None and picker.cart.cart_id not in picking_by_id:
                    self._tracked.discard(picker.cart.cart_id)
                    self.carts_left_early += 1
                    picker.abort()

        # 3. Assign idle pickers
        for sid, crew in self.pickers.items():
            for picker in crew:
                if picker.state == Picker.IDLE and picker.cart is None and self.queues[sid]:
                    cart, skus = self.queues[sid].pop(0)
                    picker.start_cart(cart, skus)

        # 4. Advance pickers
        for sid, crew in self.pickers.items():
            for picker in crew:
                serving = picker.state != Picker.IDLE
                had_cart = picker.cart
                result = picker.update(dt)
                if serving:
                    self.busy_seconds += dt
                if result is not None:
                    _sku, walk_secs = result
                    self.picks_done += 1
                    self.walk_seconds_total += walk_secs
                    self._walk_sum_sq += walk_secs * walk_secs
                # Cart finished (picker went idle with no pending picks)
                if had_cart is not None and picker.cart is None and picker.state == Picker.IDLE:
                    self._tracked.discard(had_cart.cart_id)
                    self.carts_served += 1

    # -- reporting ---------------------------------------------------------

    def cart_done(self, cart: Cart) -> bool:
        """Future dispatcher seam: True once this cart's picks are complete.
        In shadow mode nothing calls this yet."""
        return cart.cart_id not in self._tracked

    def stats(self) -> dict:
        n = self.picks_done
        mean = self.walk_seconds_total / n if n else 0.0
        var = (self._walk_sum_sq / n - mean * mean) if n > 1 else 0.0
        total_crew_seconds = self.elapsed * sum(len(c) for c in self.pickers.values())
        return {
            "picks_done": n,
            "carts_served": self.carts_served,
            "carts_left_early": self.carts_left_early,
            "walk_mean_s": mean,
            "walk_sd_s": max(0.0, var) ** 0.5,
            "busy_fraction": (
                self.busy_seconds / total_crew_seconds if total_crew_seconds else 0.0
            ),
        }

    def all_pickers(self) -> list[Picker]:
        return [p for crew in self.pickers.values() for p in crew]
