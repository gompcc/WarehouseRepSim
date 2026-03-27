"""AGV (Automated Guided Vehicle) class."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .enums import AGVState, CartState
from .constants import (
    AGV_SPEED, AGV_SPAWN_TILE, PICKUP_TIME, DROPOFF_TIME, TILE_SIZE,
)
from .pathfinding import astar

if TYPE_CHECKING:
    from .models import Cart, Tile

logger = logging.getLogger(__name__)


class AGV:
    """An Automated Guided Vehicle that moves along the warehouse graph."""

    _next_id: int = 1

    def __init__(self, pos: tuple[int, int]) -> None:
        self.agv_id: int = AGV._next_id
        AGV._next_id += 1
        self.state: AGVState = AGVState.IDLE
        self.pos: tuple[int, int] = pos
        self.target: tuple[int, int] | None = None
        self.path: list[tuple[int, int]] = []
        self.path_index: int = 0
        self.path_progress: float = 0.0
        self.carrying_cart: Cart | None = None
        self.action_timer: float = 0.0
        self.current_job = None  # Job instance managed by Dispatcher
        self.blocked_timer: float = 0.0
        self.last_reroute: float = 0.0  # kept for backward compat; see _reroute_cooldown
        self._reroute_cooldown: float = 0.0
        self.is_blocked: bool = False
        self._just_rerouted: bool = False

    def _arrive(self) -> None:
        """Reset navigation state upon reaching the destination."""
        self.pos = self.path[-1]
        self.path = []
        self.path_index = 0
        self.path_progress = 0.0
        self.target = None
        self.is_blocked = False
        self.blocked_timer = 0.0
        self._reroute_cooldown = 0.0
        self._just_rerouted = False
        if self.carrying_cart and self.carrying_cart.state == CartState.IN_TRANSIT:
            self.carrying_cart.pos = self.pos

    def reset_navigation(self) -> None:
        """Clear all path and navigation state, returning AGV to idle."""
        self.path = []
        self.path_index = 0
        self.path_progress = 0.0
        self.target = None
        self.is_blocked = False
        self.blocked_timer = 0.0
        self._reroute_cooldown = 0.0
        self._just_rerouted = False
        self.state = AGVState.IDLE
        self.current_job = None

    @property
    def next_tile(self) -> tuple[int, int] | None:
        """Return the next tile on the path, or ``None`` if at end or no path."""
        if self.path and self.path_index < len(self.path) - 1:
            return self.path[self.path_index + 1]
        return None

    def clear_blocked(self) -> None:
        """Clear the blocked state and reset timers."""
        self.is_blocked = False
        self.blocked_timer = 0.0

    def _set_path(
        self,
        route: list[tuple[int, int]],
        goal: tuple[int, int],
        state: AGVState,
    ) -> bool:
        """Apply a computed *route* and transition to *state*. Returns ``True``."""
        self.path = route
        self.path_index = 0
        self.path_progress = 0.0
        self.target = goal
        self.state = state
        return True

    def set_destination(
        self,
        goal: tuple[int, int],
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        tiles: dict[tuple[int, int], Tile],
        blocked: set[tuple[int, int]] | None = None,
    ) -> bool:
        """Plan a path to *goal*. Returns ``True`` if a path was found."""
        route = astar(graph, self.pos, goal, blocked=blocked, tiles=tiles)
        if route is None:
            return False
        return self._set_path(route, goal, AGVState.MOVING)

    def return_to_spawn(
        self,
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        tiles: dict[tuple[int, int], Tile],
    ) -> bool:
        """Plan a path back to ``AGV_SPAWN_TILE``. Returns ``True`` if a path was found."""
        route = astar(graph, self.pos, AGV_SPAWN_TILE, tiles=tiles)
        if route is None:
            return False
        return self._set_path(route, AGV_SPAWN_TILE, AGVState.RETURNING_TO_SPAWN)

    def pickup_cart(
        self,
        cart: Cart,
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        tiles: dict[tuple[int, int], Tile],
        blocked: set[tuple[int, int]] | None = None,
    ) -> bool:
        """Pathfind to *cart*'s position, then pick it up. Returns ``True`` if a path was found."""
        route = astar(graph, self.pos, cart.pos, blocked=blocked, tiles=tiles)
        if route is None:
            return False
        self.carrying_cart = cart
        return self._set_path(route, cart.pos, AGVState.MOVING_TO_PICKUP)

    def start_dropoff(
        self,
        goal: tuple[int, int],
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        tiles: dict[tuple[int, int], Tile],
        blocked: set[tuple[int, int]] | None = None,
    ) -> bool:
        """Pathfind to *goal* while carrying a cart. Returns ``True`` if a path was found."""
        route = astar(graph, self.pos, goal, blocked=blocked, tiles=tiles)
        if route is None:
            return False
        return self._set_path(route, goal, AGVState.MOVING_TO_DROPOFF)

    def reroute(
        self,
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        agvs: list[AGV],
        tiles: dict[tuple[int, int], Tile] | None = None,
    ) -> bool:
        """Re-plan path avoiding tiles occupied by or targeted by other AGVs."""
        goal = self.target or (self.path[-1] if self.path else None)
        if goal is None:
            return False
        blocked: set[tuple[int, int]] = set()
        for a in agvs:
            if a is not self:
                blocked.add(a.pos)
                # Also block their next tile to prevent head-on routing
                if a.path and a.path_index < len(a.path) - 1:
                    blocked.add(a.path[a.path_index + 1])
        route = astar(graph, self.pos, goal, blocked=blocked, tiles=tiles)
        if route is None:
            logger.debug(
                "AGV %d reroute failed: no path to %s (%d blocked tiles)",
                self.agv_id, goal, len(blocked),
            )
            return False
        remaining = self.path[self.path_index:]
        if route == remaining:
            logger.warning(
                "AGV %d reroute rejected: identical path toward %s",
                self.agv_id, goal,
            )
            return False
        self.path = route
        self.path_index = 0
        self.path_progress = 0.0
        self.blocked_timer = 0.0
        self.is_blocked = False
        logger.debug(
            "AGV %d rerouted: %d tiles toward %s", self.agv_id, len(route), goal,
        )
        return True

    def update(
        self,
        dt: float,
        agvs: list[AGV] | None = None,
        carts: list[Cart] | None = None,
        graph: dict[tuple[int, int], set[tuple[int, int]]] | None = None,
        tiles: dict[tuple[int, int], Tile] | None = None,
    ) -> None:
        """Advance along path or count down action timers."""
        # --- Pickup timer ---
        if self.state == AGVState.PICKING_UP:
            self.action_timer -= dt
            if self.action_timer <= 0:
                self.action_timer = 0.0
                if self.carrying_cart:
                    self.carrying_cart.state = CartState.IN_TRANSIT
                    self.carrying_cart.carried_by = self
                    self.carrying_cart.pos = self.pos
                self.state = AGVState.IDLE
            return

        # --- Dropoff timer ---
        if self.state == AGVState.DROPPING_OFF:
            self.action_timer -= dt
            if self.action_timer <= 0:
                self.action_timer = 0.0
                if self.carrying_cart:
                    self.carrying_cart.state = CartState.IDLE
                    self.carrying_cart.carried_by = None
                    self.carrying_cart.pos = self.pos
                    self.carrying_cart = None
                self.state = AGVState.IDLE
            return

        # --- Movement ---
        if self.state == AGVState.IDLE or not self.path:
            return

        # Allow one reroute attempt per tick (clear flag from previous tick)
        self._just_rerouted = False
        if self._reroute_cooldown > 0:
            self._reroute_cooldown = max(0.0, self._reroute_cooldown - dt)

        self.path_progress += AGV_SPEED * dt

        while self.path_progress >= 1.0 and self.path_index < len(self.path) - 1:
            next_tile = self.path[self.path_index + 1]

            # --- L1: collision check ---
            occupied = False
            if agvs:
                for other in agvs:
                    if other is not self and other.pos == next_tile:
                        occupied = True
                        break
            if (
                not occupied
                and carts
                and self.carrying_cart
                and self.carrying_cart.carried_by is self
            ):
                for cart in carts:
                    if cart.carried_by is None and cart.pos == next_tile:
                        occupied = True
                        break
            if occupied:
                logger.debug(
                    "AGV %d blocked at %s, cannot enter %s",
                    self.agv_id, self.pos, next_tile,
                )
                if graph and not self._just_rerouted:
                    if self.reroute(graph, agvs, tiles=tiles):
                        self._just_rerouted = True
                        self.path_progress = 0.0
                        break  # defer movement to next tick
                self.path_progress = 0.0
                self.is_blocked = True
                self.blocked_timer += dt
                logger.warning(
                    "AGV %d stuck at %s (%.1fs blocked)",
                    self.agv_id, self.pos, self.blocked_timer,
                )
                return

            # --- clear to advance ---
            self._just_rerouted = False
            self.is_blocked = False
            self.blocked_timer = 0.0
            self.path_progress -= 1.0
            self.path_index += 1
            self.pos = self.path[self.path_index]
            if self.carrying_cart and self.carrying_cart.state == CartState.IN_TRANSIT:
                self.carrying_cart.pos = self.pos

        # Arrived at destination?
        if self.path_index >= len(self.path) - 1:
            self._arrive()

            if self.state == AGVState.MOVING_TO_PICKUP:
                self.state = AGVState.PICKING_UP
                self.action_timer = PICKUP_TIME
            elif self.state == AGVState.MOVING_TO_DROPOFF:
                self.state = AGVState.DROPPING_OFF
                self.action_timer = DROPOFF_TIME
            else:
                self.state = AGVState.IDLE

    def get_render_pos(self) -> tuple[int, int]:
        """Return interpolated pixel position ``(cx, cy)`` for rendering."""
        if not self.path or self.path_index >= len(self.path) - 1:
            px = self.pos[0] * TILE_SIZE + TILE_SIZE // 2
            py = self.pos[1] * TILE_SIZE + TILE_SIZE // 2
            return (px, py)

        cx, cy = self.path[self.path_index]
        nx, ny = self.path[self.path_index + 1]
        t = self.path_progress
        ix = cx + (nx - cx) * t
        iy = cy + (ny - cy) * t
        px = int(ix * TILE_SIZE + TILE_SIZE // 2)
        py = int(iy * TILE_SIZE + TILE_SIZE // 2)
        return (px, py)
