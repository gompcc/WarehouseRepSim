"""Slotting strategies: the 3-arm set, aisle_proximal semantics (popular
nearest the highway/station end, dual-station aisles split with the least
popular in the middle), fibonacci staying in racking, and the world-restart
determinism the GUI comparison curves depend on.

Catalogs are built directly (not via init_catalog) so the module singleton
other tests rely on is never mutated.
"""

from collections import defaultdict

import pytest

from agv_simulation.map_builder import build_map
from agv_simulation.aisles import Catalog, Location, SLOTTING_STRATEGIES
from agv_simulation.headless import _reset_id_counters
from agv_simulation.models import Order, set_order_seed


@pytest.fixture(scope="module")
def tiles():
    return build_map()


@pytest.fixture(scope="module")
def seq(tiles):
    return Catalog(tiles, slotting="sequential")


@pytest.fixture(scope="module")
def ap(tiles):
    return Catalog(tiles, slotting="aisle_proximal")


def _walkway_of(cat: Catalog, sku: int) -> tuple[str, int]:
    """The aisle a SKU's slot lives in (Slot doesn't carry walkway_id)."""
    slot = cat.slots[sku]
    for loc in cat.locations:
        if (loc.bank, loc.run_row, loc.face, loc.level, loc.x) == (
            slot.bank, slot.run_row, slot.face, slot.level, slot.x
        ):
            return loc.walkway_id
    raise AssertionError(f"no location for SKU {sku}")


def _groups(cat: Catalog) -> dict[tuple, list[int]]:
    """(walkway_id, station) -> SKUs, using each slot's geometry."""
    loc_by_key = {
        (l.bank, l.run_row, l.face, l.level, l.x): l for l in cat.locations
    }
    groups: dict[tuple, list[int]] = defaultdict(list)
    for sku, slot in cat.slots.items():
        loc = loc_by_key[(slot.bank, slot.run_row, slot.face, slot.level, slot.x)]
        groups[(loc.walkway_id, slot.station)].append(sku)
    return groups


def test_three_strategies_and_velocity_gone(tiles):
    assert SLOTTING_STRATEGIES == ("sequential", "aisle_proximal", "fibonacci")
    with pytest.raises(ValueError):
        Catalog(tiles, slotting="velocity")


def test_sequential_is_identity(seq):
    for loc in seq.locations:
        slot = seq.slots[loc.index]
        assert (slot.x, slot.walkway_row, slot.level) == (
            loc.x, loc.walkway_row, loc.level
        )


def test_aisle_proximal_preserves_sequential_ownership(seq, ap):
    assert {s: sorted(v) for s, v in seq.station_skus.items()} == {
        s: sorted(v) for s, v in ap.station_skus.items()
    }
    # each aisle holds exactly the SKU set sequential put there
    seq_g = {k: sorted(v) for k, v in _groups(seq).items()}
    ap_g = {k: sorted(v) for k, v in _groups(ap).items()}
    assert seq_g == ap_g


def test_aisle_proximal_popular_nearest_own_station_end(ap):
    """Within every (aisle, station) group, ascending popularity rank must
    mean non-decreasing walk distance from the group's own station."""
    for (walkway, station), skus in _groups(ap).items():
        walks = [ap.walk_distance(station, sku) for sku in sorted(skus)]
        for a, b in zip(walks, walks[1:]):
            assert b >= a - 1e-9, (walkway, station)


def test_dual_station_aisle_least_popular_in_middle(ap):
    """An aisle split end-to-end between two stations fills popular-first
    from both ends, so its least popular SKUs sit interior to its hottest.

    Only true end-splits qualify (central bank): some east-bank walkways
    have two stations owning the FULL aisle span on different rack faces —
    there each face just fills popular-first from its own station's end,
    which test_aisle_proximal_popular_nearest_own_station_end covers."""
    by_walkway: dict[tuple, list[int]] = defaultdict(list)
    spans: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    for (walkway, station), skus in _groups(ap).items():
        by_walkway[walkway].extend(skus)
        xs = [ap.slots[s].x for s in skus]
        spans[walkway].append((min(xs), max(xs)))
    end_splits = []
    for w, sp in spans.items():
        if len(sp) != 2:
            continue
        (a_lo, a_hi), (b_lo, b_hi) = sorted(sp)
        overlap = a_hi - b_lo
        if overlap < 0.2 * (max(a_hi, b_hi) - a_lo):  # disjoint-ish halves
            end_splits.append(w)
    assert end_splits, "expected end-split dual-station aisles (central bank)"
    for w in end_splits:
        skus = sorted(by_walkway[w])
        xs = [ap.slots[s].x for s in skus]
        mid = (min(xs) + max(xs)) / 2.0
        n = max(len(skus) // 10, 1)
        hottest = sum(abs(ap.slots[s].x - mid) for s in skus[:n]) / n
        coldest = sum(abs(ap.slots[s].x - mid) for s in skus[-n:]) / n
        # hottest SKUs hug the ends (far from the middle), coldest the middle
        assert hottest > coldest, w


def test_fibonacci_hot_near_ring_and_in_racking(tiles, seq):
    fib = Catalog(tiles, slotting="fibonacci")
    from agv_simulation.aisles import _ring_distance

    def mean_ring(cat, skus):
        return sum(
            _ring_distance(cat.slots[s].x, cat.slots[s].walkway_row) for s in skus
        ) / len(skus)

    hot = list(range(1, 101))
    cold = list(range(len(fib.slots) - 99, len(fib.slots) + 1))
    assert mean_ring(fib, hot) < mean_ring(fib, cold)

    # every fibonacci slot is a real racking location ("stays in the aisles")
    real = {(l.bank, l.run_row, l.face, l.level, l.x) for l in seq.locations}
    for slot in fib.slots.values():
        assert (slot.bank, slot.run_row, slot.face, slot.level, slot.x) in real


def test_world_restart_determinism():
    """The GUI slotting toggle rebuilds the world; identical order streams
    across rebuilds are what make the per-strategy curves comparable."""
    def first_orders(n=5):
        _reset_id_counters()
        set_order_seed(42)
        return [Order().lines for _ in range(n)]

    a = first_orders()
    b = first_orders()
    assert a == b
    # and the stream really is seeded, not accidental global-random
    _reset_id_counters()
    set_order_seed(43)
    assert [Order().lines for _ in range(5)] != a
    # restore the shared default so other tests see a clean module state
    _reset_id_counters()
    set_order_seed(None)
