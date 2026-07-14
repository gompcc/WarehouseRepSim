"""Tests for the policy-fair spawn model (carts at Box Depot, AGVs single-file)."""

from __future__ import annotations

import pytest

from agv_simulation.constants import AGV_SPAWN_TILE, BOX_DEPOT_TIME
from agv_simulation.enums import CartState, TileType
from agv_simulation.environment import Environment


@pytest.fixture()
def env():
    return Environment()


def depot_tiles(env: Environment) -> list[tuple[int, int]]:
    return [
        pos for pos, t in env.tiles.items()
        if t.station_id == "Box_Depot" and t.tile_type == TileType.PARKING
    ]


def test_cart_spawns_at_box_depot_processing(env):
    cart = env.spawn_cart()
    assert cart is not None
    assert cart.pos in depot_tiles(env)
    assert cart.state == CartState.AT_BOX_DEPOT
    assert cart.process_timer == BOX_DEPOT_TIME


def test_depot_fills_to_capacity_then_refuses(env):
    n_tiles = len(depot_tiles(env))
    assert n_tiles == 8  # the "8 carts at the box depot" start condition
    spawned = [env.spawn_cart() for _ in range(n_tiles)]
    assert all(c is not None for c in spawned)
    assert len({c.pos for c in spawned}) == n_tiles  # all distinct tiles
    assert env.spawn_cart() is None  # depot full


def test_spawn_respects_job_reservations(env):
    # Reserve every depot tile as if in-flight carts were returning to them
    env.reserved_targets = set(depot_tiles(env))
    assert env.spawn_cart() is None
    # Free one tile — exactly one spawn fits
    env.reserved_targets.discard(sorted(env.reserved_targets)[0])
    assert env.spawn_cart() is not None
    assert env.spawn_cart() is None


def test_initial_fill_spawns_full_depot_at_t0(env):
    env.preload_remaining = 25
    env.step(0.1)
    at_depot = [c for c in env.carts if c.state == CartState.AT_BOX_DEPOT]
    assert len(at_depot) == 8
    assert env.preload_remaining == 25 - 8


def test_agvs_stream_single_file(env):
    env.agv_preload_remaining = 3
    env.step(0.1)
    assert len(env.agvs) == 1
    assert env.agvs[0].pos == AGV_SPAWN_TILE
    # Spawn tile still occupied — no second AGV however long we wait
    for _ in range(50):
        env.step(0.1)
    assert len(env.agvs) == 1
    # Once the first drives off, the next spawns
    env.agvs[0].pos = (16, 7)
    env.step(0.1)
    assert len(env.agvs) == 2
    assert env.agv_preload_remaining == 1


def test_manual_agv_spawn_blocked_when_tile_occupied(env):
    assert env.spawn_agv() is not None
    assert env.spawn_agv() is None
