"""Environment — the physical warehouse world, separated from dispatch policy.

Owns all world state (tiles, graph, AGVs, carts), cart spawning, and the
per-tick physics stepping. The Dispatcher is a pure *policy* layer on top:
it may only read world state and issue commands through AGVs; it must never
move a cart directly. The environment enforces and audits that contract:

- **Physics guard**: a cart's position may only change while it is carried
  by an AGV. Any other position change is recorded as a ``teleport`` event.
- **Stuck watchdog**: a cart that makes no lifecycle progress (same state,
  same tile, not processing, not carried) for ``stuck_threshold`` sim-seconds
  is recorded as a ``stuck`` event, re-warned every threshold interval.
- **Event log**: structured, machine-readable record of spawns, cart state
  transitions, stuck warnings, and physics violations, with per-state
  cumulative dwell times for every cart.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from .enums import AGVState, CartState, TileType
from .models import Cart
from .agv import AGV
from .map_builder import build_map, build_graph
from .aisles import init_catalog
from .layout import HighwayLayout, get_layout, set_layout
from .picker import PickerManager
from .constants import (
    PRELOAD_SPAWN_INTERVAL, AUTO_SPAWN_INTERVAL,
    STUCK_WARN_SECONDS,
    AGV_SPAWN_TILE, BOX_DEPOT_TIME,
)

if TYPE_CHECKING:
    from .models import Tile

logger = logging.getLogger(__name__)


class EventLog:
    """Structured event stream with counters; optionally mirrored to JSONL.

    Counters always accumulate, but only anomaly events (``KEEP_IN_MEMORY``)
    are retained in ``self.events`` — routine lifecycle events (cart_spawned,
    cart_state, …) would grow to tens of MB over an 8h run and nothing reads
    them back. Pass ``jsonl_path`` to capture the full stream on disk (which
    also keeps everything in memory, matching what was written).
    """

    KEEP_IN_MEMORY = {"stuck", "teleport"}

    def __init__(self, jsonl_path: str | None = None) -> None:
        self.events: list[dict] = []
        self.counters: dict[str, int] = defaultdict(int)
        self._jsonl = open(jsonl_path, "w") if jsonl_path else None

    def record(self, t: float, kind: str, **fields) -> None:
        event = {"t": round(t, 1), "kind": kind, **fields}
        self.counters[kind] += 1
        if kind in self.KEEP_IN_MEMORY or self._jsonl:
            self.events.append(event)
        if self._jsonl:
            self._jsonl.write(json.dumps(event) + "\n")

    def close(self) -> None:
        if self._jsonl:
            self._jsonl.close()
            self._jsonl = None


class Environment:
    """The physical warehouse: entities, spawning, and per-tick stepping."""

    def __init__(
        self,
        tiles: dict[tuple[int, int], Tile] | None = None,
        stuck_threshold: float = STUCK_WARN_SECONDS,
        event_jsonl: str | None = None,
        slotting: str = "sequential",
        picker_strategy: str = "static",
        picker_management: bool = False,
        layout: HighwayLayout | None = None,
    ) -> None:
        # Dynamic highway: an explicit layout is installed as the active
        # geometry before anything is built; otherwise the current
        # get_layout() singleton is used (default = the classic map).
        if layout is not None:
            set_layout(layout)
        self.layout = get_layout()
        self.tiles = tiles if tiles is not None else build_map()
        self.graph = build_graph(self.tiles)
        # 2000-SKU aisle catalog (PRD §14); slotting picks the SKU placement
        # strategy (sequential / aisle_proximal / fibonacci)
        self.catalog = init_catalog(self.tiles, slotting=slotting)
        # Pickers (PRD §14.9); strategy: static station-bound vs dynamic
        # two-pool labour sharing (outer ring / central island toggle)
        self.pickers = PickerManager(
            self.tiles, strategy=picker_strategy,
            management=picker_management,
        )
        self.agvs: list[AGV] = []
        self.carts: list[Cart] = []
        self.sim_elapsed: float = 0.0
        self.events = EventLog(jsonl_path=event_jsonl)

        # Cart spawning — carts enter the world AT the Box Depot (the box
        # machines are the physical entry point). A cart may only spawn into
        # a depot tile that is free AND not targeted by any dispatcher job
        # (the driver loop publishes job targets via ``reserved_targets``).
        self.preload_remaining: int = 0
        self.auto_spawn: bool = False
        # Graceful fleet shrink (GUI strategy toggles retarget the fleet):
        # units retire only when safe — idle AGVs, order-less depot carts
        self.agv_retire_pending: int = 0
        self.cart_retire_pending: int = 0
        self.spawn_enabled: bool = True
        self._spawn_timer: float = 0.0
        self._initial_fill_done: bool = False
        self.reserved_targets: set[tuple[int, int]] = set()
        self._depot_tiles: list[tuple[int, int]] = sorted(
            pos for pos, t in self.tiles.items()
            if t.station_id == "Box_Depot" and t.tile_type == TileType.PARKING
        )

        # AGV spawning — AGVs stream in through AGV_SPAWN_TILE one at a
        # time: the next may only spawn once the previous has left the tile.
        self.agv_preload_remaining: int = 0

        # Watchdog / audit state
        self.stuck_threshold = stuck_threshold
        self._watch: dict[int, tuple[CartState, tuple[int, int], float, float]] = {}
        self.state_time: dict[int, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        self.stuck_time: dict[int, float] = defaultdict(float)
        self._stuck_positions: dict[tuple[int, int], float] = defaultdict(float)

    # ------------------------------------------------------------------
    # Entity placement / spawning
    # ------------------------------------------------------------------

    def spawn_cart(self) -> Cart | None:
        """Spawn one cart at a free, un-targeted Box Depot tile.

        The new cart is immediately loading boxes (``AT_BOX_DEPOT`` with the
        full processing timer); an AGV must come collect it afterwards.
        Returns ``None`` when every depot tile is occupied or reserved by an
        in-flight job (e.g. a cart returning from Pack-off).
        """
        occupied = {c.pos for c in self.carts if c.carried_by is None}
        blocked = occupied | self.reserved_targets
        for spawn_pos in self._depot_tiles:
            if spawn_pos not in blocked:
                cart = Cart(spawn_pos)
                cart.state = CartState.AT_BOX_DEPOT
                cart.process_timer = BOX_DEPOT_TIME
                self.carts.append(cart)
                self.events.record(
                    self.sim_elapsed, "cart_spawned", cart=cart.cart_id, pos=spawn_pos,
                )
                logger.debug(
                    "[Env] Spawned Cart C%d at Box Depot %s (%d preload remaining)",
                    cart.cart_id, spawn_pos, max(0, self.preload_remaining - 1),
                )
                return cart
        return None

    def spawn_agv(self) -> AGV | None:
        """Spawn one AGV at ``AGV_SPAWN_TILE`` if the tile is clear.

        AGVs enter single-file: the next can only spawn once the previous
        one has driven off the spawn tile.
        """
        if any(a.pos == AGV_SPAWN_TILE for a in self.agvs):
            return None
        agv = AGV(AGV_SPAWN_TILE)
        self.agvs.append(agv)
        self.events.record(
            self.sim_elapsed, "agv_spawned", agv=agv.agv_id, pos=AGV_SPAWN_TILE,
        )
        return agv

    def retarget_fleet(self, target_agvs: int, target_carts: int) -> None:
        """Grow or shrink the live fleet toward (target_agvs, target_carts).

        Growth reuses the normal spawn pipeline (AGVs stream in single-file,
        carts enter at the Box Depot). Shrinkage is graceful: queued spawns
        are cancelled first, then surplus AGVs retire as they go idle and
        surplus carts retire when order-less at the Box Depot — never
        mid-job. Used by the GUI when a strategy toggle changes the
        optimal fleet (constants.OPTIMAL_FLEET).
        """
        agv_total = (
            len(self.agvs) + self.agv_preload_remaining - self.agv_retire_pending
        )
        delta = target_agvs - agv_total
        if delta >= 0:
            cancel = min(self.agv_retire_pending, delta)
            self.agv_retire_pending -= cancel
            self.agv_preload_remaining += delta - cancel
        else:
            need = -delta
            cancel = min(self.agv_preload_remaining, need)
            self.agv_preload_remaining -= cancel
            self.agv_retire_pending += need - cancel

        cart_total = (
            len(self.carts) + self.preload_remaining - self.cart_retire_pending
        )
        delta = target_carts - cart_total
        if delta >= 0:
            cancel = min(self.cart_retire_pending, delta)
            self.cart_retire_pending -= cancel
            self.preload_remaining += delta - cancel
        else:
            need = -delta
            cancel = min(self.preload_remaining, need)
            self.preload_remaining -= cancel
            self.cart_retire_pending += need - cancel

        self._retire_tick()

    def _retire_tick(self) -> None:
        """Remove pending-retirement units the moment it is safe to."""
        if self.agv_retire_pending > 0:
            for agv in list(self.agvs):
                if self.agv_retire_pending <= 0:
                    break
                if (
                    agv.state == AGVState.IDLE
                    and agv.current_job is None
                    and agv.carrying_cart is None
                ):
                    self.agvs.remove(agv)
                    self.agv_retire_pending -= 1
                    self.events.record(
                        self.sim_elapsed, "agv_retired", agv=agv.agv_id,
                    )
        if self.cart_retire_pending > 0:
            for cart in list(self.carts):
                if self.cart_retire_pending <= 0:
                    break
                if (
                    cart.carried_by is None
                    and cart.order is None
                    and cart.state == CartState.AT_BOX_DEPOT
                ):
                    self.carts.remove(cart)
                    self.cart_retire_pending -= 1
                    self.events.record(
                        self.sim_elapsed, "cart_retired", cart=cart.cart_id,
                    )

    def _spawn_tick(self, dt: float) -> None:
        if self.agv_retire_pending > 0 or self.cart_retire_pending > 0:
            self._retire_tick()
        # AGVs: stream in as fast as the spawn tile clears.
        if self.agv_preload_remaining > 0:
            if self.spawn_agv():
                self.agv_preload_remaining -= 1

        if not self.spawn_enabled:
            return

        # Carts: fill the whole depot at t=0 (every experiment starts with
        # the same full depot), then one per interval as tiles free up.
        if not self._initial_fill_done:
            self._initial_fill_done = True
            while self.preload_remaining > 0 and self.spawn_cart():
                self.preload_remaining -= 1
            return

        if self.preload_remaining <= 0 and not self.auto_spawn:
            return
        interval = (
            PRELOAD_SPAWN_INTERVAL if self.preload_remaining > 0 else AUTO_SPAWN_INTERVAL
        )
        self._spawn_timer += dt
        if self._spawn_timer >= interval:
            self._spawn_timer -= interval
            if self.spawn_cart() and self.preload_remaining > 0:
                self.preload_remaining -= 1

    # ------------------------------------------------------------------
    # Stepping + audit
    # ------------------------------------------------------------------

    def step(self, dt: float) -> None:
        """Advance the physical world by *dt* seconds (policy runs separately)."""
        self._spawn_tick(dt)
        for agv in self.agvs:
            agv.update(dt, self.agvs, self.carts, self.graph, self.tiles)
        for cart in self.carts:
            cart.update(dt)
        self.pickers.update(dt, self.carts)
        self.sim_elapsed += dt

    def audit(self, dt: float) -> None:
        """Audit world consistency after the policy tick (call once per tick)."""
        for cart in self.carts:
            state_name = cart.state.value
            self.state_time[cart.cart_id][state_name] += dt

            prev = self._watch.get(cart.cart_id)
            if prev is None:
                self._watch[cart.cart_id] = (cart.state, cart.pos, self.sim_elapsed, 0.0)
                continue
            prev_state, prev_pos, since, warned = prev

            # Physics guard: uncarried carts must not move on their own.
            if cart.carried_by is None and cart.pos != prev_pos:
                mover = next(
                    (a for a in self.agvs
                     if a.pos == cart.pos and a.state == AGVState.DROPPING_OFF), None,
                )
                if mover is None and prev_state not in (
                    CartState.IN_TRANSIT, CartState.TO_BOX_DEPOT,
                    CartState.IN_TRANSIT_TO_PICK, CartState.IN_TRANSIT_TO_PACKOFF,
                ):
                    self.events.record(
                        self.sim_elapsed, "teleport", cart=cart.cart_id,
                        frm=prev_pos, to=cart.pos, state=state_name,
                    )
                    logger.warning(
                        "[Env] PHYSICS VIOLATION: C%d teleported %s → %s (state=%s)",
                        cart.cart_id, prev_pos, cart.pos, state_name,
                    )

            if cart.state != prev_state:
                self.events.record(
                    self.sim_elapsed, "cart_state", cart=cart.cart_id,
                    frm=prev_state.value, to=state_name, pos=cart.pos,
                    dwell=round(self.sim_elapsed - since, 1),
                )

            # Reset the progress clock on any state or position change.
            if cart.state != prev_state or cart.pos != prev_pos:
                self._watch[cart.cart_id] = (cart.state, cart.pos, self.sim_elapsed, 0.0)
                continue

            # Stuck watchdog: no progress, not carried, not actively processing.
            # A PICKING cart with unpicked lines is being served / queued for
            # a picker — that wait is workload, not a stuck condition.
            waited = self.sim_elapsed - since
            processing = cart.process_timer > 0 or (
                cart.state == CartState.PICKING
                and not self.pickers.cart_done(cart)
            )
            if (
                cart.carried_by is None
                and not processing
                and waited >= self.stuck_threshold
                and waited - warned >= self.stuck_threshold
            ):
                self._watch[cart.cart_id] = (cart.state, cart.pos, since, waited)
                self.stuck_time[cart.cart_id] += self.stuck_threshold
                self._stuck_positions[cart.pos] += self.stuck_threshold
                self.events.record(
                    self.sim_elapsed, "stuck", cart=cart.cart_id, pos=cart.pos,
                    state=state_name, waited=round(waited, 0),
                    times_buffered=cart.times_buffered,
                )
                logger.warning(
                    "[Env] STUCK: C%d at %s in state %s for %.0fs (buffered %dx)",
                    cart.cart_id, cart.pos, state_name, waited, cart.times_buffered,
                )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def stuck_report(self) -> dict:
        """Aggregate where and how carts lost time — the bug-hunting view."""
        state_totals: dict[str, float] = defaultdict(float)
        for per_cart in self.state_time.values():
            for state, secs in per_cart.items():
                state_totals[state] += secs
        top_stuck_positions = sorted(
            self._stuck_positions.items(), key=lambda kv: -kv[1],
        )[:10]
        thrashed = sorted(
            ((c.cart_id, c.times_buffered) for c in self.carts if c.times_buffered > 0),
            key=lambda kv: -kv[1],
        )
        return {
            "stuck_events": self.events.counters.get("stuck", 0),
            "teleport_events": self.events.counters.get("teleport", 0),
            "stuck_seconds_by_cart": dict(self.stuck_time),
            "top_stuck_positions": [
                {"pos": pos, "seconds": secs} for pos, secs in top_stuck_positions
            ],
            "state_seconds_total": {k: round(v, 0) for k, v in state_totals.items()},
            "times_buffered": thrashed[:10],
        }
