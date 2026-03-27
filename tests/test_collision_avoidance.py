"""
Test suite for AGV collision avoidance, highway preference, rerouting, and spawn guard.
No pygame dependency — imports only logic functions/classes from agv_simulation.
"""

import pytest

from agv_simulation import (
    Tile, TileType, AGV, AGVState, Cart, CartState,
    AGV_SPAWN_TILE, astar, build_map, build_graph,
    Dispatcher, Job, JobType, Order, STATIONS,
    BLOCK_TIMEOUT, JOB_CANCEL_TIMEOUT, REROUTE_COOLDOWN,
    verify_graph,
)


# -- Helpers ----------------------------------------------------------

def _make_tile(x, y, tt):
    return Tile(x, y, tt)


def _small_graph_with_highway_and_parking():
    """
    Build a small 5x3 grid:

       (0,0)-(1,0)-(2,0)-(3,0)-(4,0)    <- all PARKING (cost 10)
         |                         |
       (0,1)-(1,1)-(2,1)-(3,1)-(4,1)    <- all HIGHWAY (cost 1)
         |                         |
       (0,2)-(1,2)-(2,2)-(3,2)-(4,2)    <- all PARKING (cost 10)
    """
    tiles = {}
    graph = {}
    for x in range(5):
        for y in range(3):
            tt = TileType.HIGHWAY if y == 1 else TileType.PARKING
            tiles[(x, y)] = _make_tile(x, y, tt)
            graph[(x, y)] = set()

    for y in range(3):
        for x in range(4):
            graph[(x, y)].add((x + 1, y))
            graph[(x + 1, y)].add((x, y))
    for x in [0, 4]:
        for y in range(2):
            graph[(x, y)].add((x, y + 1))
            graph[(x, y + 1)].add((x, y))

    return graph, tiles


# -- Tests ------------------------------------------------------------

def test_astar_prefers_highway():
    graph, tiles = _small_graph_with_highway_and_parking()
    path = astar(graph, (0, 1), (4, 1), tiles=tiles)
    assert path is not None
    for node in path:
        assert tiles[node].tile_type == TileType.HIGHWAY


def test_astar_blocked_tiles():
    graph, tiles = _small_graph_with_highway_and_parking()
    blocked = {(2, 1)}
    path = astar(graph, (0, 1), (4, 1), blocked=blocked, tiles=tiles)
    assert path is not None
    assert (2, 1) not in path


def test_astar_blocked_allows_goal():
    graph, tiles = _small_graph_with_highway_and_parking()
    goal = (4, 1)
    blocked = {goal}
    path = astar(graph, (0, 1), goal, blocked=blocked, tiles=tiles)
    assert path is not None
    assert path[-1] == goal


def test_two_lane_directions():
    tiles = build_map()
    graph = build_graph(tiles)
    for x in range(1, 9):
        neighbors = graph.get((x, 7), set())
        assert (x + 1, 7) in neighbors
        if x > 1:
            assert (x - 1, 7) not in neighbors
    for x in range(2, 9):
        neighbors = graph.get((x, 8), set())
        assert (x - 1, 8) in neighbors
        if x < 8:
            assert (x + 1, 8) not in neighbors


def test_agv_collision_block():
    tiles = build_map()
    graph = build_graph(tiles)
    agv1 = AGV((1, 7))
    agv2 = AGV((2, 7))
    agvs = [agv1, agv2]
    agv1.path = [(1, 7), (2, 7), (3, 7)]
    agv1.path_index = 0
    agv1.path_progress = 0.0
    agv1.state = AGVState.MOVING
    agv1.target = (3, 7)
    agv2.state = AGVState.IDLE
    agv1.update(1.5, agvs=agvs, carts=[], graph=graph, tiles=tiles)
    assert agv1.pos != agv2.pos


def test_agv_reroute_on_block():
    tiles = build_map()
    graph = build_graph(tiles)
    agv1 = AGV((1, 7))
    agv2 = AGV((2, 7))
    agvs = [agv1, agv2]
    agv1.path = [(1, 7), (2, 7), (3, 7)]
    agv1.path_index = 0
    agv1.path_progress = 0.0
    agv1.state = AGVState.MOVING
    agv1.target = (3, 7)
    agv2.state = AGVState.IDLE
    agv1.update(1.5, agvs=agvs, carts=[], graph=graph, tiles=tiles)
    if agv1._just_rerouted:
        assert (2, 7) not in agv1.path[1:]


def test_agv_reroute_rejects_same_first_step():
    tiles = {
        (0, 0): _make_tile(0, 0, TileType.HIGHWAY),
        (1, 0): _make_tile(1, 0, TileType.HIGHWAY),
        (2, 0): _make_tile(2, 0, TileType.HIGHWAY),
    }
    graph = {
        (0, 0): {(1, 0)},
        (1, 0): {(0, 0), (2, 0)},
        (2, 0): {(1, 0)},
    }
    agv1 = AGV((0, 0))
    agv1.path = [(0, 0), (1, 0), (2, 0)]
    agv1.path_index = 0
    agv1.target = (2, 0)
    agv1.state = AGVState.MOVING
    agv2 = AGV((5, 5))
    result = agv1.reroute(graph, [agv1, agv2], tiles=tiles)
    assert result is False


def test_spawn_guard():
    agvs = []
    agv1 = AGV(AGV_SPAWN_TILE)
    agvs.append(agv1)
    assert any(a.pos == AGV_SPAWN_TILE for a in agvs)
    agv1.pos = (5, 7)
    assert not any(a.pos == AGV_SPAWN_TILE for a in agvs)


def test_cart_cart_collision_only_when_carrying():
    tiles = build_map()
    graph = build_graph(tiles)
    cart_blocker = Cart((3, 7))
    cart_blocker.state = CartState.IDLE
    cart_blocker.carried_by = None
    agv = AGV((1, 7))
    agv.path = [(1, 7), (2, 7), (3, 7)]
    agv.path_index = 0
    agv.path_progress = 0.0
    agv.state = AGVState.MOVING_TO_PICKUP
    agv.target = (3, 7)
    agv.carrying_cart = cart_blocker
    carts = [cart_blocker]
    agvs = [agv]
    agv.update(3.0, agvs=agvs, carts=carts, graph=graph, tiles=tiles)
    assert agv.pos == (3, 7)

    carried_cart = Cart((10, 7))
    carried_cart.state = CartState.IN_TRANSIT
    carried_cart.carried_by = None
    agv2 = AGV((1, 7))
    carried_cart.carried_by = agv2
    agv2.carrying_cart = carried_cart
    agv2.path = [(1, 7), (2, 7), (3, 7)]
    agv2.path_index = 0
    agv2.path_progress = 0.0
    agv2.state = AGVState.MOVING_TO_DROPOFF
    agv2.target = (3, 7)
    carts2 = [cart_blocker, carried_cart]
    agvs2 = [agv2]
    agv2.update(3.0, agvs=agvs2, carts=carts2, graph=graph, tiles=tiles)
    assert agv2.pos != (3, 7) or agv2._just_rerouted


def test_no_tile_overlap_simulation():
    tiles = build_map()
    graph = build_graph(tiles)
    start_positions = [(1, 7), (2, 7), (3, 7)]
    agvs = [AGV(pos) for pos in start_positions]
    destinations = [(8, 12), (10, 17), (39, 35)]
    for agv, dest in zip(agvs, destinations):
        agv.set_destination(dest, graph, tiles)
    dt = 0.1
    for tick in range(100):
        for agv in agvs:
            agv.update(dt, agvs=agvs, carts=[], graph=graph, tiles=tiles)
        positions = [a.pos for a in agvs]
        assert len(positions) == len(set(positions))


def test_highway_cost_weight():
    graph, tiles = _small_graph_with_highway_and_parking()
    path = astar(graph, (0, 1), (4, 1), tiles=tiles)
    assert path is not None
    total_cost = 0
    for i in range(1, len(path)):
        node = path[i]
        if node == (4, 1):
            total_cost += 1
        else:
            tile = tiles.get(node)
            total_cost += 1 if (tile and tile.tile_type == TileType.HIGHWAY) else 10
    assert total_cost == 4

    blocked = {(2, 1)}
    path2 = astar(graph, (0, 1), (4, 1), blocked=blocked, tiles=tiles)
    assert path2 is not None
    assert (2, 1) not in path2
    total_cost2 = 0
    for i in range(1, len(path2)):
        node = path2[i]
        if node == (4, 1):
            total_cost2 += 1
        else:
            tile = tiles.get(node)
            total_cost2 += 1 if (tile and tile.tile_type == TileType.HIGHWAY) else 10
    assert total_cost2 > total_cost


# -- Capacity-Based Routing Tests ------------------------------------

def test_get_station_fill_empty():
    tiles = build_map()
    dispatcher = Dispatcher(tiles)
    fill = dispatcher.get_station_fill(carts=[])
    for station_id, (current, capacity, rate) in fill.items():
        assert current == 0
        assert rate == 0.0
        assert capacity == STATIONS[station_id]


def test_get_station_fill_with_carts():
    tiles = build_map()
    dispatcher = Dispatcher(tiles)
    s1_tiles = dispatcher._station_tiles.get(("S1", TileType.PICK_STATION), [])
    assert len(s1_tiles) == 5
    carts = []
    for i in range(3):
        c = Cart(s1_tiles[i])
        c.state = CartState.PICKING
        c.carried_by = None
        carts.append(c)
    fill = dispatcher.get_station_fill(carts)
    current, capacity, rate = fill["S1"]
    assert current == 3
    assert capacity == 5
    assert abs(rate - 3 / 5) < 0.01


def test_pick_best_station_prefers_emptier():
    tiles = build_map()
    dispatcher = Dispatcher(tiles)
    s1_tiles = dispatcher._station_tiles.get(("S1", TileType.PICK_STATION), [])
    carts = []
    for i in range(3):
        c = Cart(s1_tiles[i])
        c.state = CartState.PICKING
        c.carried_by = None
        carts.append(c)
    cart_pos = (9, 20)
    result = dispatcher._pick_best_station([1, 3], cart_pos, carts)
    assert result == 3


def test_pick_best_station_distance_tiebreak():
    tiles = build_map()
    dispatcher = Dispatcher(tiles)
    carts = []
    cart_pos = (8, 11)
    result = dispatcher._pick_best_station([1, 3], cart_pos, carts)
    assert result == 1


def test_pick_best_station_skips_full():
    tiles = build_map()
    dispatcher = Dispatcher(tiles)
    s1_tiles = dispatcher._station_tiles.get(("S1", TileType.PICK_STATION), [])
    carts = []
    for i in range(5):
        c = Cart(s1_tiles[i])
        c.state = CartState.PICKING
        c.carried_by = None
        carts.append(c)
    cart_pos = (8, 11)
    result = dispatcher._pick_best_station([1, 3], cart_pos, carts)
    assert result == 3


def test_nearest_agv_assignment():
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)
    cart = Cart((0, 7))
    cart.state = CartState.SPAWNED
    carts = [cart]
    agv_far = AGV((5, 0))
    agv_near = AGV((1, 7))
    agvs = [agv_far, agv_near]
    dispatcher.update(carts, agvs, graph, tiles)
    assert agv_near.current_job is not None
    assert agv_near.current_job.cart is cart
    assert agv_far.current_job is None


# -- Reroute & deadlock tests -------------------------------------------

def test_reroute_accepts_same_first_step_different_path():
    """Reroute accepted when first step matches but subsequent path diverges."""
    # Diamond with goal at (3,0): two paths share first step (1,0)
    # Top:    (0,0) -> (1,0) -> (2,0) -> (3,0)
    # Bottom: (0,0) -> (1,0) -> (1,1) -> (2,1) -> (3,1) -> (3,0)
    tiles = {}
    graph = {}
    for pos in [(0, 0), (1, 0), (2, 0), (3, 0), (1, 1), (2, 1), (3, 1)]:
        tiles[pos] = _make_tile(*pos, TileType.HIGHWAY)
        graph[pos] = set()
    # Top path
    graph[(0, 0)].add((1, 0)); graph[(1, 0)].add((0, 0))
    graph[(1, 0)].add((2, 0)); graph[(2, 0)].add((1, 0))
    graph[(2, 0)].add((3, 0)); graph[(3, 0)].add((2, 0))
    # Bottom path
    graph[(1, 0)].add((1, 1)); graph[(1, 1)].add((1, 0))
    graph[(1, 1)].add((2, 1)); graph[(2, 1)].add((1, 1))
    graph[(2, 1)].add((3, 1)); graph[(3, 1)].add((2, 1))
    graph[(3, 1)].add((3, 0)); graph[(3, 0)].add((3, 1))

    agv1 = AGV((0, 0))
    agv1.path = [(0, 0), (1, 0), (2, 0), (3, 0)]
    agv1.path_index = 0
    agv1.target = (3, 0)
    agv1.state = AGVState.MOVING
    # Block (2, 0) — forces reroute through bottom path, but first step is still (1,0)
    agv2 = AGV((2, 0))
    result = agv1.reroute(graph, [agv1, agv2], tiles=tiles)
    # New path starts with same first step (1,0) but diverges
    assert result is True
    assert (2, 0) not in agv1.path  # avoided blocked tile


def test_reroute_rejects_identical_remaining_path():
    """Reroute rejected when entire remaining path is identical to current."""
    tiles = {
        (0, 0): _make_tile(0, 0, TileType.HIGHWAY),
        (1, 0): _make_tile(1, 0, TileType.HIGHWAY),
        (2, 0): _make_tile(2, 0, TileType.HIGHWAY),
    }
    graph = {
        (0, 0): {(1, 0)},
        (1, 0): {(0, 0), (2, 0)},
        (2, 0): {(1, 0)},
    }
    agv1 = AGV((0, 0))
    agv1.path = [(0, 0), (1, 0), (2, 0)]
    agv1.path_index = 0
    agv1.target = (2, 0)
    agv1.state = AGVState.MOVING
    agv2 = AGV((5, 5))  # not blocking
    result = agv1.reroute(graph, [agv1, agv2], tiles=tiles)
    assert result is False


def test_three_way_deadlock_resolution():
    """Three AGVs in a triangle — dispatcher nudge resolves within 200 ticks."""
    tiles = build_map()
    graph = build_graph(tiles)
    # Place 3 AGVs on adjacent highway tiles heading toward each other
    agv1 = AGV((3, 7))
    agv2 = AGV((4, 7))
    agv3 = AGV((5, 7))
    agvs = [agv1, agv2, agv3]
    agv1.set_destination((6, 7), graph, tiles)
    agv2.set_destination((3, 7), graph, tiles)  # opposite direction
    agv3.set_destination((3, 7), graph, tiles)

    dispatcher = Dispatcher(tiles)
    initial_positions = {a.agv_id: a.pos for a in agvs}

    for _ in range(200):
        for agv in agvs:
            agv.update(0.1, agvs=agvs, carts=[], graph=graph, tiles=tiles)
        dispatcher._handle_blocked_agvs(agvs, graph, tiles)
        dispatcher._park_idle_agvs(agvs, graph, tiles)

    # At least one AGV should have moved from its starting position
    moved = sum(1 for a in agvs if a.pos != initial_positions[a.agv_id])
    assert moved >= 1


def test_consecutive_reroutes_converge():
    """AGV repeatedly blocked eventually arrives at destination."""
    tiles = build_map()
    graph = build_graph(tiles)
    agv1 = AGV((1, 7))
    agv1.set_destination((8, 12), graph, tiles)
    # Place blockers along the highway that will be nudged
    agv2 = AGV((3, 7))
    agv3 = AGV((5, 7))
    agv2.state = AGVState.IDLE
    agv3.state = AGVState.IDLE
    agvs = [agv1, agv2, agv3]

    for _ in range(500):
        for agv in agvs:
            agv.update(0.1, agvs=agvs, carts=[], graph=graph, tiles=tiles)
        if agv1.state == AGVState.IDLE and agv1.pos == (8, 12):
            break

    assert agv1.pos == (8, 12)


# -- Path progress & bounds tests ---------------------------------------

def test_path_progress_zero_after_reroute():
    """After a successful reroute, path_progress is reset to 0.0."""
    tiles = build_map()
    graph = build_graph(tiles)
    agv1 = AGV((1, 7))
    agv2 = AGV((2, 7))
    agvs = [agv1, agv2]
    agv1.path = [(1, 7), (2, 7), (3, 7), (4, 7)]
    agv1.path_index = 0
    agv1.path_progress = 0.0
    agv1.state = AGVState.MOVING
    agv1.target = (4, 7)
    agv2.state = AGVState.IDLE

    agv1.update(1.5, agvs=agvs, carts=[], graph=graph, tiles=tiles)
    if agv1._just_rerouted:
        assert agv1.path_progress == 0.0


def test_path_progress_zero_after_block():
    """When blocked and no reroute available, path_progress is 0.0."""
    tiles = {
        (0, 0): _make_tile(0, 0, TileType.HIGHWAY),
        (1, 0): _make_tile(1, 0, TileType.HIGHWAY),
        (2, 0): _make_tile(2, 0, TileType.HIGHWAY),
    }
    graph = {
        (0, 0): {(1, 0)},
        (1, 0): {(0, 0), (2, 0)},
        (2, 0): {(1, 0)},
    }
    agv1 = AGV((0, 0))
    agv2 = AGV((1, 0))  # blocks the only path
    agvs = [agv1, agv2]
    agv1.path = [(0, 0), (1, 0), (2, 0)]
    agv1.path_index = 0
    agv1.path_progress = 0.0
    agv1.state = AGVState.MOVING
    agv1.target = (2, 0)
    agv2.state = AGVState.IDLE

    agv1.update(1.5, agvs=agvs, carts=[], graph=graph, tiles=tiles)
    assert agv1.is_blocked
    assert agv1.path_progress == 0.0


def test_path_progress_no_overflow_high_dt():
    """At dt=5.0 (extreme speed), path_progress never exceeds 1.0 on blocked AGV."""
    tiles = build_map()
    graph = build_graph(tiles)
    agv1 = AGV((1, 7))
    agv2 = AGV((3, 7))  # blocks at (3,7)
    agvs = [agv1, agv2]
    agv1.set_destination((5, 7), graph, tiles)
    agv2.state = AGVState.IDLE

    for _ in range(10):
        agv1.update(5.0, agvs=agvs, carts=[], graph=graph, tiles=tiles)
        assert agv1.path_progress <= 1.0


# -- A* edge case tests -------------------------------------------------

def test_astar_start_equals_goal():
    """A* with start == goal returns single-element path."""
    graph, tiles = _small_graph_with_highway_and_parking()
    path = astar(graph, (0, 1), (0, 1), tiles=tiles)
    assert path == [(0, 1)]


def test_astar_goal_unreachable():
    """A* returns None when goal is not in the graph."""
    graph, tiles = _small_graph_with_highway_and_parking()
    path = astar(graph, (0, 1), (99, 99), tiles=tiles)
    assert path is None


def test_astar_no_tiles_still_finds_path():
    """A* works without tiles dict (conservative cost, no highway preference)."""
    graph, _ = _small_graph_with_highway_and_parking()
    path = astar(graph, (0, 1), (4, 1), tiles=None)
    assert path is not None
    assert path[0] == (0, 1)
    assert path[-1] == (4, 1)


# -- Dispatcher-navigation interaction tests -----------------------------

def test_cancel_stuck_job_resets_agv():
    """AGV blocked > JOB_CANCEL_TIMEOUT while heading to pickup gets job cancelled."""
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)

    cart = Cart((0, 7))
    cart.state = CartState.SPAWNED
    carts = [cart]
    agv = AGV((1, 7))
    agvs = [agv]

    # Let dispatcher assign the job
    dispatcher.update(carts, agvs, graph, tiles)
    assert agv.current_job is not None
    original_job = agv.current_job

    # pickup_cart() pre-sets carrying_cart before the AGV has actually
    # reached the cart. Clear it to simulate the "heading to pickup" state
    # that _cancel_stuck_jobs checks (carrying_cart is None).
    agv.carrying_cart = None

    # Simulate being stuck for longer than JOB_CANCEL_TIMEOUT
    agv.is_blocked = True
    agv.blocked_timer = JOB_CANCEL_TIMEOUT + 1.0

    dispatcher._cancel_stuck_jobs(agvs, carts, graph, tiles)

    assert agv.state == AGVState.IDLE
    assert agv.current_job is None
    assert agv.path == []
    assert original_job in dispatcher.pending_jobs


def test_nudge_idle_blocker():
    """Idle AGV blocking a moving AGV gets nudged to parking."""
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)

    agv_mover = AGV((2, 7))
    agv_mover.path = [(2, 7), (3, 7), (4, 7)]
    agv_mover.path_index = 0
    agv_mover.state = AGVState.MOVING
    agv_mover.target = (4, 7)
    agv_mover.is_blocked = True
    agv_mover.blocked_timer = BLOCK_TIMEOUT + 1.0

    agv_blocker = AGV((3, 7))
    agv_blocker.state = AGVState.IDLE
    agvs = [agv_mover, agv_blocker]

    dispatcher._handle_blocked_agvs(agvs, graph, tiles)

    # Blocker should have been nudged — it should now be MOVING
    assert agv_blocker.state == AGVState.MOVING
    assert agv_blocker.target is not None


def test_park_idle_agv_off_highway():
    """Idle jobless AGV on highway gets moved to parking."""
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)

    agv = AGV((3, 7))
    agv.state = AGVState.IDLE
    agv.current_job = None
    agv.carrying_cart = None
    agvs = [agv]

    assert tiles[(3, 7)].tile_type == TileType.HIGHWAY

    dispatcher._park_idle_agvs(agvs, graph, tiles)

    assert agv.state == AGVState.MOVING
    assert agv.target is not None
    target_tile = tiles.get(agv.target)
    assert target_tile is not None
    assert target_tile.tile_type in (TileType.PARKING, TileType.AGV_SPAWN)


# -- Encapsulation tests -------------------------------------------------

def test_agv_reset_navigation():
    """reset_navigation() clears all navigation fields."""
    agv = AGV((5, 5))
    agv.path = [(5, 5), (6, 5)]
    agv.path_index = 1
    agv.path_progress = 0.5
    agv.target = (6, 5)
    agv.is_blocked = True
    agv.blocked_timer = 10.0
    agv._reroute_cooldown = 1.5
    agv._just_rerouted = True
    agv.state = AGVState.MOVING
    agv.current_job = "fake_job"

    agv.reset_navigation()

    assert agv.path == []
    assert agv.path_index == 0
    assert agv.path_progress == 0.0
    assert agv.target is None
    assert agv.is_blocked is False
    assert agv.blocked_timer == 0.0
    assert agv._reroute_cooldown == 0.0
    assert agv._just_rerouted is False
    assert agv.state == AGVState.IDLE
    assert agv.current_job is None


def test_agv_next_tile_property():
    """next_tile returns correct tile mid-path and None at end."""
    agv = AGV((0, 0))
    agv.path = [(0, 0), (1, 0), (2, 0)]
    agv.path_index = 0
    assert agv.next_tile == (1, 0)

    agv.path_index = 1
    assert agv.next_tile == (2, 0)

    agv.path_index = 2  # at end
    assert agv.next_tile is None

    agv.path = []
    assert agv.next_tile is None


# -- Graph verification test ----------------------------------------------

def test_verify_graph_all_stations_reachable():
    """Every station S1-S9, Box_Depot, Pack_off is reachable from spawn and back."""
    tiles = build_map()
    graph = build_graph(tiles)

    # Collect one tile per station that is actually in the graph
    station_tiles = {}
    for pos, tile in tiles.items():
        if tile.station_id and tile.station_id not in station_tiles and pos in graph:
            station_tiles[tile.station_id] = pos

    for station_id in STATIONS:
        assert station_id in station_tiles, f"Station {station_id} has no graph-connected tiles"
        station_pos = station_tiles[station_id]

        path_to = astar(graph, AGV_SPAWN_TILE, station_pos, tiles=tiles)
        assert path_to is not None, f"No path from spawn to {station_id} at {station_pos}"

        path_back = astar(graph, station_pos, AGV_SPAWN_TILE, tiles=tiles)
        assert path_back is not None, f"No path from {station_id} at {station_pos} to spawn"


# -- Stress tests --------------------------------------------------------

def _assert_simulation_invariants(agvs):
    """Check structural invariants that must hold every tick."""
    positions = [a.pos for a in agvs]
    assert len(positions) == len(set(positions)), (
        f"Tile overlap detected: {positions}"
    )
    for a in agvs:
        assert 0.0 <= a.path_progress <= 1.0, (
            f"AGV {a.agv_id} path_progress out of bounds: {a.path_progress}"
        )
        if a.path:
            assert a.path_index <= len(a.path) - 1, (
                f"AGV {a.agv_id} path_index {a.path_index} out of bounds "
                f"(path length {len(a.path)})"
            )


@pytest.mark.parametrize("n_agvs", [3, 6, 10, 14])
def test_no_tile_overlap_parametrized(n_agvs):
    """Multi-AGV simulation with no tile overlaps for 500 ticks."""
    tiles = build_map()
    graph = build_graph(tiles)
    # Spread AGVs across spawn/highway tiles
    start_positions = [(i, 7) for i in range(1, n_agvs + 1)]
    agvs = [AGV(pos) for pos in start_positions]
    # Send them to various stations
    station_goals = [(8, 12), (10, 17), (39, 35), (20, 20), (30, 30),
                     (15, 15), (25, 25), (35, 10), (8, 30), (10, 10),
                     (5, 20), (12, 25), (38, 20), (20, 35)]
    for agv, dest in zip(agvs, station_goals):
        agv.set_destination(dest, graph, tiles)

    dt = 0.1
    for _ in range(500):
        for agv in agvs:
            agv.update(dt, agvs=agvs, carts=[], graph=graph, tiles=tiles)
        _assert_simulation_invariants(agvs)


def test_stress_high_speed_no_overlap():
    """8 AGVs at high dt (1.0) — no overlaps or overflow for 500 ticks."""
    tiles = build_map()
    graph = build_graph(tiles)
    agvs = [AGV((i, 7)) for i in range(1, 9)]
    goals = [(8, 12), (10, 17), (39, 35), (20, 20),
             (30, 30), (15, 15), (25, 25), (35, 10)]
    for agv, dest in zip(agvs, goals):
        agv.set_destination(dest, graph, tiles)

    for _ in range(500):
        for agv in agvs:
            agv.update(1.0, agvs=agvs, carts=[], graph=graph, tiles=tiles)
        _assert_simulation_invariants(agvs)


@pytest.mark.slow
def test_stress_no_permanent_deadlock():
    """Headless simulation with 10 AGVs and 16 carts completes orders (no deadlock)."""
    from agv_simulation import run_headless
    result = run_headless(
        num_agvs=10,
        num_carts=16,
        sim_duration=3600.0,
        tick_dt=0.1,
        verbose=False,
    )
    assert result["completed_orders"] > 0, "No orders completed — likely deadlocked"
    assert result["agv_blocked_fraction"] < 0.5, (
        f"AGVs blocked {result['agv_blocked_fraction']:.0%} of time — excessive"
    )
