"""Zone-batched order release: ONE station per side takes all of an
order's lines on that side (~3 stops instead of ~8 under flat 20-line
orders). The stations-per-order lever — 2-pager recommendation #4: the
tax is set upstream by the WMS, free to fix in software.
"""

import pytest

from agv_simulation.aisles import init_catalog
from agv_simulation.map_builder import build_map
from agv_simulation.models import Order, set_order_book, set_order_seed

SIDE_GROUPS = {
    "west": {"S1", "S3"},
    "central": {"S2", "S4", "S6", "S8"},
    "east": {"S5", "S7", "S9"},
}


@pytest.fixture
def fresh_orders():
    """Deterministic sampled orders (no book) with reset id counters."""
    set_order_book(None)
    set_order_seed(42)
    Order._next_id = 1
    Order.sizes = []
    Order.station_counts = []
    yield
    set_order_seed(None)


def _visited_ids(order) -> set[str]:
    return {f"S{n}" for n in order.stations_to_visit}


def test_off_by_default_and_matches_zone_derivation(fresh_orders):
    cat = init_catalog(build_map())
    assert cat.batch_release is False
    order = Order()
    for num, skus in order.skus_by_station.items():
        for sku in skus:
            assert cat.station_of(sku) == f"S{num}"


def test_batched_visits_at_most_one_station_per_side(fresh_orders):
    init_catalog(build_map(), batch_release=True)
    for _ in range(30):
        order = Order()
        visited = _visited_ids(order)
        for side, group in SIDE_GROUPS.items():
            assert len(visited & group) <= 1, (side, visited)
        assert len(order.stations_to_visit) <= 3
        # every sampled line survives the re-bucketing
        rebucketed = sorted(
            s for skus in order.skus_by_station.values() for s in skus
        )
        assert rebucketed == sorted(order.lines)


def test_batched_release_map_never_crosses_the_highway(fresh_orders):
    cat = init_catalog(build_map(), batch_release=True)
    skus = list(cat.slots)[::97]  # a spread of the catalog
    assignment = cat.batched_release_map(skus, order_id=7)
    for sku, sid in assignment.items():
        assert cat.station_side[sid] == cat.slots[sku].bank


def test_batched_cuts_stations_per_order(fresh_orders):
    init_catalog(build_map())
    for _ in range(20):
        Order()
    baseline = sum(Order.station_counts) / len(Order.station_counts)

    Order._next_id = 1
    Order.station_counts = []
    init_catalog(build_map(), batch_release=True)
    for _ in range(20):
        Order()
    batched = sum(Order.station_counts) / len(Order.station_counts)

    assert baseline > 6.0   # flat 20-line orders tour most stations
    assert batched <= 3.0   # at most one stop per side
    assert Order.sizes  # lines stat still recorded


def test_rotation_spreads_orders_across_all_stations(fresh_orders):
    cat = init_catalog(build_map(), batch_release=True)
    hit: set[str] = set()
    for _ in range(24):  # lcm(2, 4, 3) = 12 order ids; 24 for safety
        hit |= _visited_ids(Order())
    assert hit == set(cat.station_pos), hit


def test_rotation_is_deterministic(fresh_orders):
    cat = init_catalog(build_map(), batch_release=True)
    skus = list(cat.slots)[:50]
    assert cat.batched_release_map(skus, 5) == cat.batched_release_map(skus, 5)
    # different order ids rotate same-side choices
    a = set(cat.batched_release_map(skus, 5).values())
    b = set(cat.batched_release_map(skus, 6).values())
    assert a != b


def test_walk_stats_price_side_wide_pools():
    zone_cat = init_catalog(build_map())
    zone_avg = dict(zone_cat.station_avg_walk_s())
    zone_far = dict(zone_cat.longest_walk_m())

    batch_cat = init_catalog(build_map(), batch_release=True)
    batch_avg = batch_cat.station_avg_walk_s()
    batch_far = batch_cat.longest_walk_m()

    for sid in zone_avg:
        # a station's pickers now roam the whole side: expected pick time
        # and worst-case walk can only grow vs the own-zone pool
        assert batch_avg[sid] >= zone_avg[sid] - 1e-9, sid
        assert batch_far[sid] >= zone_far[sid] - 1e-9, sid
    # every same-side station prices the identical side-wide worst case
    for group in SIDE_GROUPS.values():
        pool_sizes = {
            len(batch_cat.side_skus(batch_cat.station_side[sid]))
            for sid in group
        }
        assert len(pool_sizes) == 1
