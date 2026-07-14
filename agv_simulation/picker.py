"""Pickers: per-station humans who walk the product aisles (PRD §14.6/14.9).

Pickers react to carts sitting at pick stations in ``PICKING`` state, walk
each of the cart's SKU lines (one line per round trip), and — when wired to
the Dispatcher (``gating=True``, the normal mode; there is no flat-timer
fallback) — gate the cart's departure: ``cart_done(cart)`` is the release
rule, and the picker calls ``order.complete_station()`` on the last line.

Pick lists come from the cart's SKU order (``order.skus_remaining_at``,
resume-safe after buffering). Carts without an order (manual/edge cases) get
a sampled list of ``max(1, round(N(4, 2)))`` SKUs from the station's zone.
Walking time follows the calibrated aisle geometry (μ 30 s, σ 10 s round
trip; see ``aisles.WALK_TIME_*``) plus ``PICK_GRAB_TIME`` at the slot.

Pickers use their own RNG stream so they never perturb the seeded order
stream used by the dispatch-strategy experiments.
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from .enums import CartState, TileType
from .constants import (
    PICK_GRAB_TIME, PICKERS_PER_STATION,
    PICKS_PER_VISIT_MEAN, PICKS_PER_VISIT_SD,
)
from .aisles import get_catalog, walk_time_seconds

if TYPE_CHECKING:
    from .models import Cart, Tile

logger = logging.getLogger(__name__)

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
        # Orderless carts served once must not be re-sampled while they
        # linger in PICKING (order-driven carts are guarded by remaining=0)
        self._served_orderless: set[int] = set()
        # True once a Dispatcher is wired to gate cart release on cart_done()
        # (set by Dispatcher.__init__); False = shadow mode, GUI label only.
        self.gating = False

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
        """Shadow-mode fallback for carts without a SKU order."""
        cat = get_catalog()
        zone = cat.station_skus.get(station_id, [])
        if not zone:
            return []
        n = max(1, round(self.rng.gauss(PICKS_PER_VISIT_MEAN, PICKS_PER_VISIT_SD)))
        return self.rng.sample(zone, min(n, len(zone)))

    def _pick_list(self, cart: Cart, station_id: str) -> list[int]:
        """The SKU lines this cart needs here: the order's *remaining* lines
        (resume-safe after buffering), or a sampled list when orderless."""
        order = cart.order
        if order is not None and hasattr(order, "skus_remaining_at"):
            return order.skus_remaining_at(int(station_id[1:]))
        return self._sample_picks(station_id)

    # -- main tick -------------------------------------------------------

    def update(self, dt: float, carts: list[Cart]) -> None:
        self.elapsed += dt
        picking_by_id: dict[int, Cart] = {
            c.cart_id: c
            for c in carts
            if c.state == CartState.PICKING and c.carried_by is None
        }

        # 1. New arrivals → derive their pick lists, queue them. A cart with
        # nothing to pick here is NOT tracked: a served cart that lingers in
        # PICKING (e.g. its next station is full) must stay released —
        # re-queueing it with an empty list would deadlock it forever.
        for cart in picking_by_id.values():
            if cart.cart_id in self._tracked or cart.cart_id in self._served_orderless:
                continue
            sid = self.station_of_pos.get(cart.pos)
            if sid is None:
                continue
            picks = self._pick_list(cart, sid)
            if not picks:
                continue
            self._tracked.add(cart.cart_id)
            self.queues[sid].append((cart, picks))
        self._served_orderless &= set(picking_by_id)  # forget once they leave

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
                    done_sku, walk_secs = result
                    self.picks_done += 1
                    self.walk_seconds_total += walk_secs
                    self._walk_sum_sq += walk_secs * walk_secs
                    if had_cart is not None and had_cart.order is not None and hasattr(
                        had_cart.order, "mark_picked"
                    ):
                        had_cart.order.mark_picked(done_sku)
                # Cart finished (picker went idle with no pending picks)
                if had_cart is not None and picker.cart is None and picker.state == Picker.IDLE:
                    self._tracked.discard(had_cart.cart_id)
                    self.carts_served += 1
                    self._complete_station_if_done(had_cart)
                    if had_cart.order is None:
                        self._served_orderless.add(had_cart.cart_id)

    def _complete_station_if_done(self, cart: Cart) -> None:
        """Mark the station complete on the order once no lines remain here.

        Called when a picker finishes a cart's list. Resume-safe: a cart
        buffered away mid-picking and brought back only completes once its
        genuinely last line at this station is picked."""
        order = cart.order
        if order is None or not hasattr(order, "skus_remaining_at"):
            return
        sid = self.station_of_pos.get(cart.pos)
        if sid is None:
            return
        num = int(sid[1:])
        if not order.skus_remaining_at(num) and num not in order.completed_stations:
            order.complete_station(num)
            logger.info(
                "[Picker] C%d: all %d lines picked at %s — station complete",
                cart.cart_id, order.items_at_station(num), sid,
            )

    # -- reporting ---------------------------------------------------------

    def cart_done(self, cart: Cart) -> bool:
        """Dispatcher release seam: True once this cart's picks here are done.

        Robust to tick ordering: a cart is NOT done while queued or being
        served, nor while its order still has unpicked lines at this station
        (covers the instant between entering PICKING and being queued)."""
        if cart.cart_id in self._tracked:
            return False
        order = cart.order
        if order is not None and hasattr(order, "skus_remaining_at"):
            sid = self.station_of_pos.get(cart.pos)
            if sid is not None:
                return not order.skus_remaining_at(int(sid[1:]))
        return True

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
