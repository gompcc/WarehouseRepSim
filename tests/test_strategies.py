"""Tests for the toggleable dispatch strategy modules."""

from __future__ import annotations

import itertools
import random

import pytest

from agv_simulation.map_builder import build_map, build_graph
from agv_simulation.models import Order, set_order_seed
from agv_simulation.dispatcher import Dispatcher
from agv_simulation.strategies import (
    StrategyConfig, DistanceMap, OrderSequencing,
)
from agv_simulation.strategies.global_assignment import min_cost_assignment
from agv_simulation.enums import TileType


@pytest.fixture(scope="module")
def world():
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)
    dist_map = DistanceMap(graph, dispatcher._station_tiles)
    return tiles, graph, dispatcher, dist_map


# ----------------------------------------------------------------------
# Seeded order stream (controlled environment)
# ----------------------------------------------------------------------

def test_seeded_orders_reproducible():
    set_order_seed(42)
    Order._next_id = 1
    first = [Order().picks for _ in range(20)]
    Order._next_id = 1
    second = [Order().picks for _ in range(20)]
    assert first == second
    set_order_seed(None)


def test_order_n_identical_regardless_of_creation_order():
    """Order N's contents depend only on (seed, N) — not on timing."""
    set_order_seed(7)
    Order._next_id = 5
    o5 = Order()
    Order._next_id = 5
    Order()  # other orders created in between must not matter
    Order()
    Order._next_id = 5
    o5_again = Order()
    assert o5.picks == o5_again.picks
    set_order_seed(None)


# ----------------------------------------------------------------------
# Directed distance map
# ----------------------------------------------------------------------

def test_distance_map_prices_cross_side_trips(world):
    """Manhattan underprices right-bank → left-bank trips ~2x: the banks
    only connect via the top/bottom highways. Same-bank moves ride the
    bidirectional parking ladder and stay close to Manhattan."""
    _, _, _, dist_map = world
    s7_pos = (53, 23)  # an S7 pick tile
    same_bank = dist_map.hops_to_station(s7_pos, "S9")   # Manhattan ~10
    cross_bank = dist_map.hops_to_station(s7_pos, "S3")  # Manhattan ~32
    assert same_bank <= 12
    assert cross_bank > 45  # real directed route: up col 52, row 7, down col 23

def test_distance_map_all_stations_reachable(world):
    _, graph, _, dist_map = world
    start = (29, 5)  # Box Depot parking
    for i in range(1, 10):
        assert dist_map.hops_to_station(start, f"S{i}") != float("inf")
    assert dist_map.hops_to_station(start, "Pack_off") != float("inf")


# ----------------------------------------------------------------------
# Hungarian assignment
# ----------------------------------------------------------------------

def _brute_force_min(cost):
    n, m = len(cost), len(cost[0])
    k = min(n, m)
    best = float("inf")
    rows_iter = itertools.permutations(range(n), k) if n <= m else [range(n)]
    if n <= m:
        for cols in itertools.permutations(range(m), n):
            best = min(best, sum(cost[i][cols[i]] for i in range(n)))
    else:
        for rows in itertools.permutations(range(n), m):
            best = min(best, sum(cost[rows[j]][j] for j in range(m)))
    return best


def test_hungarian_matches_brute_force_square():
    rng = random.Random(1)
    for _ in range(25):
        n = rng.randint(2, 5)
        cost = [[rng.uniform(0, 100) for _ in range(n)] for _ in range(n)]
        pairs = min_cost_assignment(cost)
        total = sum(cost[r][c] for r, c in pairs)
        assert total == pytest.approx(_brute_force_min(cost))


def test_hungarian_rectangular_both_orientations():
    rng = random.Random(2)
    for rows, cols in [(3, 6), (6, 3), (2, 5), (5, 2)]:
        cost = [[rng.uniform(0, 50) for _ in range(cols)] for _ in range(rows)]
        pairs = min_cost_assignment(cost)
        assert len(pairs) == min(rows, cols)
        # No row or col used twice
        assert len({r for r, _ in pairs}) == len(pairs)
        assert len({c for _, c in pairs}) == len(pairs)
        total = sum(cost[r][c] for r, c in pairs)
        assert total == pytest.approx(_brute_force_min(cost))


def test_hungarian_beats_or_ties_greedy():
    """The classic greedy failure: nearest-first forces a bad global match."""
    cost = [
        [1.0, 2.0],
        [2.0, 100.0],
    ]
    # Greedy row 0 takes col 0 (cost 1) forcing row 1 → col 1 (100): total 101
    pairs = min_cost_assignment(cost)
    total = sum(cost[r][c] for r, c in pairs)
    assert total == pytest.approx(4.0)  # optimal: r0→c1, r1→c0


# ----------------------------------------------------------------------
# Order sequencing
# ----------------------------------------------------------------------

def test_sequencing_prefers_forward_stations(world):
    _, _, _, dist_map = world
    seq = OrderSequencing(dist_map)

    class FakeCart:
        pos = (53, 23)  # at S7

    # Remaining: S5 (behind) and S9 (ahead) — window must lead with S9
    ordered = seq.order_candidates(FakeCart(), [5, 9])
    assert ordered[0] == 9


# ----------------------------------------------------------------------
# Toggle isolation
# ----------------------------------------------------------------------

def test_default_config_is_baseline(world):
    tiles, _, _, _ = world
    d = Dispatcher(tiles)
    assert not d.strategies.any_active()
    assert d.strategies.active_names() == []


def test_config_active_names():
    cfg = StrategyConfig(eta_reservations=True, order_sequencing=True)
    assert cfg.active_names() == ["eta", "sequencing"]
