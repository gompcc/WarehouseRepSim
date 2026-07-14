"""Data models: Cart, Order, Job, Tile, and station capacities."""

from __future__ import annotations

import random

from .enums import CartState, JobType, TileType
from .constants import (
    CART_COLOR_SPAWNED, CART_COLOR_IN_TRANSIT, CART_COLOR_PROCESSING,
    CART_COLOR_WAITING, CART_COLOR_COMPLETED, CART_COLOR_IDLE,
    ORDER_LINES_MEAN, ORDER_LINES_SD,
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
        self.times_buffered: int = 0

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


_order_seed: int | None = None
_order_book: list[list[int]] | None = None


def set_order_seed(seed: int | None) -> None:
    """Fix the order stream: with a seed, order N's contents are identical
    across runs regardless of *when* it is created — required for fair A/B
    comparison of dispatch strategies against the same demand."""
    global _order_seed
    _order_seed = seed


def set_order_book(book: list[list[int]] | None) -> None:
    """Serve orders from a fixed pregenerated book (the canonical demand;
    see ``orderbook.py``). Order N takes the book entry at
    ``(N-1 + offset) % len(book)`` where the offset derives from the order
    seed — arms stay PAIRED per seed (identical flow), while different
    seeds read different windows of the same demand for error bars.
    ``None`` restores per-order random sampling."""
    global _order_book
    _order_book = book


class Order:
    """A picking order: 1 or many lines, grouped by owning station.

    Glossary (canonical, user-defined): a **line** is a SKU which is part
    of an order, no matter the quantity; a line is the same as a **pick**
    (one picker round trip picks one line). An order consists of
    ``max(1, round(N(20, 9)))`` distinct lines, sampled popularity-weighted
    in SKU space — demand is independent of slot placement, so every
    slotting strategy faces the identical order stream (EXPERIMENT_DESIGN.md
    fairness rule). ``stations_to_visit`` is derived from where the catalog
    places each sampled SKU. ``lines`` is the flat SKU-id list; pickers
    mark lines done via :meth:`mark_picked`.
    """

    _next_id: int = 1

    def __init__(self) -> None:
        self.order_id: int = Order._next_id
        Order._next_id += 1
        from .aisles import get_catalog  # runtime import: models loads first
        catalog = get_catalog()

        if _order_book:
            # Canonical fixed demand: order N is a book entry (per-seed
            # window offset keeps arms paired while seeds vary)
            offset = (_order_seed or 0) * 997 % len(_order_book)
            skus = _order_book[(self.order_id - 1 + offset) % len(_order_book)]
        else:
            rng = (
                random.Random(_order_seed * 1_000_003 + self.order_id)
                if _order_seed is not None
                else random
            )
            n_lines = max(1, round(rng.gauss(ORDER_LINES_MEAN, ORDER_LINES_SD)))
            # Popularity-weighted: hot SKUs (low ids) appear in many
            # orders, which is what makes slotting strategies matter.
            skus = catalog.sample_skus(n_lines, rng)

        self.lines: list[int] = []                     # flat SKU ids, one per line
        self.skus_by_station: dict[int, list[int]] = {}
        for sku in skus:
            num = int(catalog.station_of(sku)[1:])
            self.skus_by_station.setdefault(num, []).append(sku)
            self.lines.append(sku)

        self.stations_to_visit: list[int] = sorted(self.skus_by_station)
        self.completed_stations: list[int] = []
        self.picked_skus: set[int] = set()
        self.packed: bool = False  # True once the cart has reached Pack-off

    def lines_at_station(self, station_num: int) -> int:
        """Return the number of lines to pick at *station_num*."""
        return len(self.skus_by_station.get(station_num, []))

    def lines_remaining_at(self, station_num: int) -> list[int]:
        """Unpicked lines at *station_num* (drives picker work + release)."""
        return [
            s for s in self.skus_by_station.get(station_num, [])
            if s not in self.picked_skus
        ]

    def mark_picked(self, sku: int) -> None:
        """Record one line as picked (called by the station's picker)."""
        self.picked_skus.add(sku)

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
        self.failed_agvs: set[int] = set()  # AGV IDs that failed this job
        self.retarget_count: int = 0


# Station capacities
STATIONS: dict[str, int] = {
    "S1": 5, "S2": 4, "S3": 4, "S4": 4,
    "S5": 4, "S6": 4, "S7": 4, "S8": 4, "S9": 4,
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
