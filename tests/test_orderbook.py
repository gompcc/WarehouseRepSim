"""Canonical order book: fixed 15h x 3000 lines/hr demand (user spec).

Every arm must face the same order flow; product frequency must follow the
half-normal popularity curve; order sizes ~ N(20, 9) with a floor of 1.
"""

import pytest

from agv_simulation.constants import NUM_SKUS
from agv_simulation.map_builder import build_map
from agv_simulation.aisles import init_catalog
from agv_simulation.models import Order, set_order_book, set_order_seed
from agv_simulation.orderbook import (
    TOTAL_LINES, generate_order_book, sku_frequencies,
)


@pytest.fixture(scope="module")
def book():
    return generate_order_book()


def test_book_is_deterministic(book):
    assert generate_order_book() == book


def test_book_volume_and_size_distribution(book):
    sizes = [len(o) for o in book]
    total = sum(sizes)
    assert TOTAL_LINES <= total < TOTAL_LINES + max(sizes)
    mean = total / len(book)
    sd = (sum((s - mean) ** 2 for s in sizes) / len(sizes)) ** 0.5
    assert 19.0 < mean < 21.0, mean   # target mu 20
    assert 8.0 < sd < 10.0, sd        # target sd 9
    assert min(sizes) >= 1
    for order in book:
        assert len(set(order)) == len(order)  # distinct lines per order
        assert all(1 <= sku <= NUM_SKUS for sku in order)


def test_frequency_is_flat_across_skus(book):
    """Demand is FLAT (user spec 2026-07-15): every SKU equally likely,
    so the first and last popularity centiles see the same traffic."""
    freq = sku_frequencies(book)
    assert sum(freq.values()) == sum(len(o) for o in book)
    top = sum(freq.get(s, 0) for s in range(1, 101)) / 100
    bottom = sum(freq.get(s, 0) for s in range(1901, 2001)) / 100
    assert 0.8 < top / bottom < 1.25, (top, bottom)
    # ~45k lines over 2000 SKUs -> everything gets ordered at least once
    assert len(freq) == 2000


def test_orders_consume_book_identically_across_arms(book):
    tiles = build_map()
    streams = {}
    for slotting in ("sequential", "aisle_proximal", "fibonacci"):
        init_catalog(tiles, slotting=slotting)
        set_order_seed(42)
        set_order_book(book)
        Order._next_id = 1
        try:
            streams[slotting] = [Order().lines for _ in range(50)]
        finally:
            set_order_book(None)
            set_order_seed(None)
    assert streams["sequential"] == streams["aisle_proximal"] == streams["fibonacci"]
    # Order N is literally book entry N (+ seed-42 window offset)
    offset = 42 * 997 % len(book)
    assert streams["sequential"][0] == book[offset]


def test_seeds_read_different_windows(book):
    tiles = build_map()
    init_catalog(tiles)
    def stream(seed):
        set_order_seed(seed)
        set_order_book(book)
        Order._next_id = 1
        try:
            return [Order().lines for _ in range(20)]
        finally:
            set_order_book(None)
            set_order_seed(None)
    assert stream(11) != stream(77)   # different demand windows
    assert stream(11) == stream(11)   # but each is reproducible
