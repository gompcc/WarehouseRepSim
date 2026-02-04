"""Data models: Cart, Order, Job, Tile, and station capacities."""

from __future__ import annotations

import random

from .enums import CartState, JobType, TileType
from .constants import (
    CART_COLOR_SPAWNED, CART_COLOR_IN_TRANSIT, CART_COLOR_PROCESSING,
    CART_COLOR_WAITING, CART_COLOR_COMPLETED, CART_COLOR_IDLE,
)


class Cart:
    """A cart that carries items through the warehouse."""

    _next_id: int = 1

    def __init__(self, pos: tuple[int, int]) -> None:
        self.cart_id: int = Cart._next_id
        Cart._next_id += 1
        self.pos: tuple[int, int] = pos
        self.state: CartState = CartState.SPAWNED
        self.carried_by = None  # AGV instance or None
        self.order: Order | None = None
        self.process_timer: float = 0.0

    def update(self, dt: float) -> None:
        """Decrement process_timer when at a processing station."""
        if self.state in (CartState.AT_BOX_DEPOT, CartState.PICKING, CartState.AT_PACKOFF):
            if self.process_timer > 0:
                self.process_timer -= dt
                if self.process_timer < 0:
                    self.process_timer = 0.0

    def get_color(self) -> tuple[int, int, int]:
        """Return the RGB color for this cart's current state."""
        if self.state == CartState.SPAWNED:
            return CART_COLOR_SPAWNED
        elif self.state in (
            CartState.TO_BOX_DEPOT, CartState.IN_TRANSIT_TO_PICK,
            CartState.IN_TRANSIT_TO_PACKOFF, CartState.IN_TRANSIT,
        ):
            return CART_COLOR_IN_TRANSIT
        elif self.state in (CartState.AT_BOX_DEPOT, CartState.PICKING, CartState.AT_PACKOFF):
            return CART_COLOR_PROCESSING
        elif self.state == CartState.WAITING_FOR_STATION:
            return CART_COLOR_WAITING
        elif self.state == CartState.COMPLETED:
            return CART_COLOR_COMPLETED
        else:
            return CART_COLOR_IDLE


class Order:
    """A picking order assigned to a cart."""

    _next_id: int = 1

    def __init__(self) -> None:
        self.order_id: int = Order._next_id
        Order._next_id += 1
        length = random.randint(1, 9)
        self.picks: list[int] = [random.randint(1, 9) for _ in range(length)]
        self.stations_to_visit: list[int] = sorted(set(self.picks))
        self.completed_stations: list[int] = []

    def items_at_station(self, station_num: int) -> int:
        """Return the number of items to pick at *station_num*."""
        return self.picks.count(station_num)

    def next_station(self) -> int | None:
        """Return the next unvisited station number, or ``None``."""
        for s in self.stations_to_visit:
            if s not in self.completed_stations:
                return s
        return None

    def complete_station(self, station_num: int) -> None:
        """Mark *station_num* as completed."""
        self.completed_stations.append(station_num)

    def all_picked(self) -> bool:
        """Return ``True`` if all stations have been visited."""
        return len(self.completed_stations) == len(self.stations_to_visit)


class Job:
    """A transport job linking a cart to a target position."""

    _next_id: int = 1

    def __init__(
        self,
        job_type: JobType,
        cart: Cart,
        target_pos: tuple[int, int],
        station_id: str | None = None,
    ) -> None:
        self.job_id: int = Job._next_id
        Job._next_id += 1
        self.job_type: JobType = job_type
        self.cart: Cart = cart
        self.target_pos: tuple[int, int] = target_pos
        self.station_id: str | None = station_id
        self.assigned_agv = None


# Station capacities
STATIONS: dict[str, int] = {
    "S1": 5, "S2": 4, "S3": 4, "S4": 4,
    "S5": 3, "S6": 4, "S7": 4, "S8": 4, "S9": 4,
    "Box_Depot": 8, "Pack_off": 4,
}


class Tile:
    """One square on the warehouse grid."""

    def __init__(
        self,
        x: int,
        y: int,
        tile_type: TileType,
        station_id: str | None = None,
    ) -> None:
        self.x: int = x
        self.y: int = y
        self.tile_type: TileType = tile_type
        self.station_id: str | None = station_id
