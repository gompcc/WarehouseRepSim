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
from .constants import (
    CART_SPAWN_TILES, PRELOAD_SPAWN_INTERVAL, AUTO_SPAWN_INTERVAL,
    STUCK_WARN_SECONDS, DEFAULT_AGV_SPOTS,
)

if TYPE_CHECKING:
    from .models import Tile

logger = logging.getLogger(__name__)


class EventLog:
    """Structured event stream with counters; optionally mirrored to JSONL."""

    def __init__(self, jsonl_path: str | None = None) -> None:
        self.events: list[dict] = []
        self.counters: dict[str, int] = defaultdict(int)
        self._jsonl = open(jsonl_path, "w") if jsonl_path else None

    def record(self, t: float, kind: str, **fields) -> None:
        event = {"t": round(t, 1), "kind": kind, **fields}
        self.events.append(event)
        self.counters[kind] += 1
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
    ) -> None:
        self.tiles = tiles if tiles is not None else build_map()
        self.graph = build_graph(self.tiles)
        self.agvs: list[AGV] = []
        self.carts: list[Cart] = []
        self.sim_elapsed: float = 0.0
        self.events = EventLog(jsonl_path=event_jsonl)

        # Cart spawning (preload cadence, then optional slow auto-spawn)
        self.preload_remaining: int = 0
        self.auto_spawn: bool = False
        self.spawn_enabled: bool = True
        self._spawn_timer: float = 0.0

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

    def place_agvs(self, count: int, spots: list[tuple[int, int]] | None = None) -> None:
        """Place *count* AGVs at fixed spots, overflowing to free parking tiles."""
        spots = spots if spots is not None else DEFAULT_AGV_SPOTS
        used = {a.pos for a in self.agvs}
        extra = [
            pos for pos in self.graph
            if self.tiles[pos].tile_type in (TileType.PARKING, TileType.AGV_SPAWN)
            and self.tiles[pos].station_id is None
            and pos not in set(spots) | used
        ]
        for i in range(count):
            if i < len(spots) and spots[i] not in used:
                pos = spots[i]
            elif extra:
                pos = extra.pop(0)
            else:
                logger.warning("No parking spot for AGV %d", i + 1)
                continue
            agv = AGV(pos)
            self.agvs.append(agv)
            self.events.record(self.sim_elapsed, "agv_spawned", agv=agv.agv_id, pos=pos)

    def spawn_cart(self) -> Cart | None:
        """Spawn one cart at the first free spawn tile, or ``None`` if all occupied."""
        occupied = {c.pos for c in self.carts if c.carried_by is None}
        for spawn_pos in CART_SPAWN_TILES:
            if spawn_pos not in occupied:
                cart = Cart(spawn_pos)
                self.carts.append(cart)
                self.events.record(
                    self.sim_elapsed, "cart_spawned", cart=cart.cart_id, pos=spawn_pos,
                )
                logger.info(
                    "[Env] Spawned Cart C%d at %s (%d preload remaining)",
                    cart.cart_id, spawn_pos, max(0, self.preload_remaining - 1),
                )
                return cart
        return None

    def _spawn_tick(self, dt: float) -> None:
        if not self.spawn_enabled:
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
            waited = self.sim_elapsed - since
            processing = cart.process_timer > 0
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
