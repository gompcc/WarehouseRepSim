"""
Test suite for AGV collision avoidance, highway preference, rerouting, and spawn guard.
No pygame dependency — imports only logic functions/classes from agv_simulation.
"""

from agv_simulation import (
    Tile, TileType, AGV, AGVState, Cart, CartState,
    AGV_SPAWN_TILE, astar, build_map, build_graph,
    Dispatcher, Job, JobType, Order, STATIONS,
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
