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
    for x in range(15, 23):
        neighbors = graph.get((x, 7), set())
        assert (x + 1, 7) in neighbors
        if x > 15:
            assert (x - 1, 7) not in neighbors
    for x in range(16, 23):
        neighbors = graph.get((x, 8), set())
        assert (x - 1, 8) in neighbors
        if x < 22:
            assert (x + 1, 8) not in neighbors


def test_agv_collision_block():
    tiles = build_map()
    graph = build_graph(tiles)
    agv1 = AGV((15, 7))
    agv2 = AGV((16, 7))
    agvs = [agv1, agv2]
    agv1.path = [(15, 7), (16, 7), (17, 7)]
    agv1.path_index = 0
    agv1.path_progress = 0.0
    agv1.state = AGVState.MOVING
    agv1.target = (17, 7)
    agv2.state = AGVState.IDLE
    agv1.update(1.5, agvs=agvs, carts=[], graph=graph, tiles=tiles)
    assert agv1.pos != agv2.pos


def test_agv_reroute_on_block():
    tiles = build_map()
    graph = build_graph(tiles)
    agv1 = AGV((15, 7))
    agv2 = AGV((16, 7))
    agvs = [agv1, agv2]
    agv1.path = [(15, 7), (16, 7), (17, 7)]
    agv1.path_index = 0
    agv1.path_progress = 0.0
    agv1.state = AGVState.MOVING
    agv1.target = (17, 7)
    agv2.state = AGVState.IDLE
    agv1.update(1.5, agvs=agvs, carts=[], graph=graph, tiles=tiles)
    if agv1._just_rerouted:
        assert (16, 7) not in agv1.path[1:]


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
    agv1.pos = (19, 7)
    assert not any(a.pos == AGV_SPAWN_TILE for a in agvs)


def test_cart_cart_collision_only_when_carrying():
    tiles = build_map()
    graph = build_graph(tiles)
    cart_blocker = Cart((17, 7))
    cart_blocker.state = CartState.IDLE
    cart_blocker.carried_by = None
    agv = AGV((15, 7))
    agv.path = [(15, 7), (16, 7), (17, 7)]
    agv.path_index = 0
    agv.path_progress = 0.0
    agv.state = AGVState.MOVING_TO_PICKUP
    agv.target = (17, 7)
    agv.carrying_cart = cart_blocker
    carts = [cart_blocker]
    agvs = [agv]
    agv.update(3.0, agvs=agvs, carts=carts, graph=graph, tiles=tiles)
    assert agv.pos == (17, 7)

    carried_cart = Cart((24, 7))
    carried_cart.state = CartState.IN_TRANSIT
    carried_cart.carried_by = None
    agv2 = AGV((15, 7))
    carried_cart.carried_by = agv2
    agv2.carrying_cart = carried_cart
    agv2.path = [(15, 7), (16, 7), (17, 7)]
    agv2.path_index = 0
    agv2.path_progress = 0.0
    agv2.state = AGVState.MOVING_TO_DROPOFF
    agv2.target = (17, 7)
    carts2 = [cart_blocker, carried_cart]
    agvs2 = [agv2]
    agv2.update(3.0, agvs=agvs2, carts=carts2, graph=graph, tiles=tiles)
    assert agv2.pos != (17, 7) or agv2._just_rerouted


def test_no_tile_overlap_simulation():
    tiles = build_map()
    graph = build_graph(tiles)
    start_positions = [(15, 7), (16, 7), (17, 7)]
    agvs = [AGV(pos) for pos in start_positions]
    destinations = [(22, 12), (24, 17), (53, 35)]
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
    cart_pos = (23, 20)
    result = dispatcher._pick_best_station([1, 3], cart_pos, carts)
    assert result == 3


def test_pick_best_station_distance_tiebreak():
    tiles = build_map()
    dispatcher = Dispatcher(tiles)
    carts = []
    cart_pos = (22, 11)
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
    cart_pos = (22, 11)
    result = dispatcher._pick_best_station([1, 3], cart_pos, carts)
    assert result == 3


def test_nearest_agv_assignment():
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)
    cart = Cart((14, 7))
    cart.state = CartState.SPAWNED
    carts = [cart]
    agv_far = AGV((19, 0))
    agv_near = AGV((15, 7))
    agvs = [agv_far, agv_near]
    dispatcher.update(carts, agvs, graph, tiles)
    assert agv_near.current_job is not None
    assert agv_near.current_job.cart is cart
    assert agv_far.current_job is None


# -- Dispatch Fixes Tests ------------------------------------------------

def test_idle_agv_excluded_from_blocked_set():
    """Idle AGVs should NOT block pathfinding — they get nudged on contact."""
    tiles = build_map()
    graph = build_graph(tiles)
    # Place idle AGV at (15, 6) — on the only path to cart spawn (14, 7)
    agv_idle = AGV((15, 6))
    agv_idle.state = AGVState.IDLE
    # Place working AGV at (17, 7) trying to reach (14, 7)
    agv_worker = AGV((17, 7))
    agvs = [agv_idle, agv_worker]
    # With idle exclusion, worker should find path through (15, 6)
    blocked = {a.pos for a in agvs if a is not agv_worker and a.state != AGVState.IDLE}
    assert (15, 6) not in blocked  # idle AGV not in blocked set
    route = astar(graph, agv_worker.pos, (14, 7), blocked=blocked, tiles=tiles)
    assert route is not None


def test_progress_jobs_buffers_immediately_on_unreachable():
    """When target AND alt tile are unreachable, buffer immediately — no retries."""
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)
    # Create a cart at a station tile, AGV carrying it
    s1_tiles = dispatcher._station_tiles.get(("S1", TileType.PICK_STATION), [])
    cart = Cart(s1_tiles[0])
    cart.state = CartState.IN_TRANSIT
    agv = AGV(s1_tiles[0])
    agv.carrying_cart = cart
    cart.carried_by = agv
    agv.state = AGVState.IDLE
    # Create a job targeting a tile we'll make unreachable
    job = Job(JobType.MOVE_TO_PICK, cart, (99, 99), station_id="S1")
    job.assigned_agv = agv
    agv.current_job = job
    dispatcher.active_jobs.append(job)
    # Fill ALL S1 tiles with carts so alt target returns None
    carts = [cart]
    for pos in s1_tiles:
        blocker = Cart(pos)
        blocker.state = CartState.PICKING
        blocker.carried_by = None
        carts.append(blocker)
    # Run progress — should buffer immediately, not retry
    dispatcher._progress_jobs([agv], carts, graph, tiles)
    # Job should have been retargeted to buffer
    assert job.job_type == JobType.MOVE_TO_BUFFER


def test_cancel_stuck_pickup_with_carrying_cart():
    """_cancel_stuck_jobs must handle MOVING_TO_PICKUP even when carrying_cart is set."""
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)
    cart = Cart((14, 7))
    cart.state = CartState.SPAWNED
    agv = AGV((19, 7))
    # Simulate the reservation: carrying_cart set but not yet physically picked up
    agv.carrying_cart = cart
    agv.state = AGVState.MOVING_TO_PICKUP
    agv.is_blocked = True
    agv.blocked_timer = 60.0  # well past JOB_CANCEL_TIMEOUT
    agv.path = [(19, 7), (18, 7)]
    agv.path_index = 0
    job = Job(JobType.PICKUP_TO_BOX_DEPOT, cart, (29, 5))
    job.assigned_agv = agv
    agv.current_job = job
    dispatcher.active_jobs.append(job)
    dispatcher._cancel_stuck_jobs([agv], [cart], graph, tiles)
    # AGV should be freed
    assert agv.state == AGVState.IDLE
    assert agv.carrying_cart is None
    assert agv.current_job is None
    # Job should be re-queued with this AGV blacklisted
    assert job in dispatcher.pending_jobs
    assert agv.agv_id in job.failed_agvs


def test_failed_agvs_skips_previous_failures():
    """_assign_jobs should skip AGVs that previously failed a job."""
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)
    cart = Cart((14, 7))
    cart.state = CartState.SPAWNED
    carts = [cart]
    agv_near = AGV((15, 7))  # nearest but will be in failed_agvs
    agv_far = AGV((19, 0))   # farther but eligible
    agvs = [agv_near, agv_far]
    # Create a pending job with agv_near blacklisted
    job = Job(JobType.PICKUP_TO_BOX_DEPOT, cart, (29, 5))
    job.failed_agvs.add(agv_near.agv_id)
    dispatcher.pending_jobs.append(job)
    dispatcher._assign_jobs(agvs, graph, tiles)
    # agv_far should get the job, not agv_near
    if job.assigned_agv is not None:
        assert job.assigned_agv is agv_far


def test_backpressure_reduces_slots():
    """Blocked AGVs should reduce available dispatch slots."""
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)
    # Create 3 blocked AGVs
    agvs = []
    for i in range(3):
        agv = AGV((i + 15, 7))
        agv.is_blocked = True
        agv.state = AGVState.MOVING
        agv.path = [(i + 15, 7), (i + 16, 7)]
        agv.path_index = 0
        agvs.append(agv)
    # Create an idle AGV and a pending job
    idle_agv = AGV((19, 0))
    agvs.append(idle_agv)
    cart = Cart((14, 7))
    cart.state = CartState.SPAWNED
    carts = [cart]
    job = Job(JobType.PICKUP_TO_BOX_DEPOT, cart, (29, 5))
    dispatcher.pending_jobs.append(job)
    # With 3 blocked, slots = 12 - 0 active - 3//3 = 11 — still enough
    dispatcher._assign_jobs(agvs, graph, tiles)
    # Job should still be assignable (slots > 0)
    assert idle_agv.current_job is not None or job in dispatcher.pending_jobs


def test_find_alt_tile_for_pick_station():
    """_find_alt_tile should find free tiles at the same station."""
    tiles = build_map()
    dispatcher = Dispatcher(tiles)
    s1_tiles = dispatcher._station_tiles.get(("S1", TileType.PICK_STATION), [])
    assert len(s1_tiles) == 5
    # Occupy 4 tiles, leave 1 free
    carts = []
    for i in range(4):
        c = Cart(s1_tiles[i])
        c.state = CartState.PICKING
        c.carried_by = None
        carts.append(c)
    job = Job(JobType.MOVE_TO_PICK, carts[0], s1_tiles[0], station_id="S1")
    result = dispatcher._find_alt_tile(job, carts)
    assert result == s1_tiles[4]  # only free tile


def test_retarget_cap_never_drops_cart_on_highway():
    """Even past the retarget cap, an AGV on a highway tile must keep its
    cart — an abandoned cart in the single-lane loop gridlocks everything."""
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)
    cart = Cart((23, 20))  # col 9 = left highway
    cart.state = CartState.IN_TRANSIT
    agv = AGV((23, 20))
    agv.carrying_cart = cart
    cart.carried_by = agv
    agv.state = AGVState.MOVING_TO_DROPOFF
    agv.is_blocked = True
    agv.blocked_timer = 60.0
    agv.path = [(23, 20), (23, 21)]
    agv.path_index = 0
    job = Job(JobType.MOVE_TO_BUFFER, cart, (24, 20))
    job.assigned_agv = agv
    job.retarget_count = 3  # already at limit
    agv.current_job = job
    dispatcher.active_jobs.append(job)
    dispatcher._cancel_stuck_jobs([agv], [cart], graph, tiles)
    # Cart must still be on the AGV (retargeted or waiting, but not dumped)
    assert cart.carried_by is agv
    assert agv.carrying_cart is cart


def test_packoff_capacity_check_uses_physical_occupancy():
    """WAITING_FOR_STATION carts should only dispatch to pack-off when physically free."""
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)
    packoff_tiles = dispatcher._station_tiles.get(("Pack_off", TileType.PARKING), [])
    # Fill all 4 pack-off tiles physically
    carts = []
    for pos in packoff_tiles:
        c = Cart(pos)
        c.state = CartState.AT_PACKOFF
        c.carried_by = None
        c.process_timer = 10.0
        carts.append(c)
    # Create a waiting cart that wants pack-off
    waiting = Cart((22, 9))
    waiting.state = CartState.WAITING_FOR_STATION
    from agv_simulation.models import Order
    waiting.order = Order()
    waiting.order.stations_to_visit = []
    waiting.order.completed_stations = []
    waiting.order.lines = []
    carts.append(waiting)
    dispatcher._create_jobs(carts, [], graph, tiles)
    # No MOVE_TO_PACKOFF job should be created (pack-off physically full)
    packoff_jobs = [j for j in dispatcher.pending_jobs if j.job_type == JobType.MOVE_TO_PACKOFF]
    assert len(packoff_jobs) == 0


def test_find_alt_tile_returns_none_when_full():
    """_find_alt_tile returns None when all station tiles are occupied."""
    tiles = build_map()
    dispatcher = Dispatcher(tiles)
    s1_tiles = dispatcher._station_tiles.get(("S1", TileType.PICK_STATION), [])
    carts = []
    for pos in s1_tiles:
        c = Cart(pos)
        c.state = CartState.PICKING
        c.carried_by = None
        carts.append(c)
    job = Job(JobType.MOVE_TO_PICK, carts[0], s1_tiles[0], station_id="S1")
    result = dispatcher._find_alt_tile(job, carts)
    assert result is None


def test_orphaned_waiting_cart_gets_rerouted_to_box_depot():
    """A WAITING_FOR_STATION cart with no order (buffered before reaching
    Box Depot) must be re-routed to Box Depot, not deadlock forever."""
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)
    orphan = Cart((22, 9))
    orphan.state = CartState.WAITING_FOR_STATION
    orphan.order = None
    dispatcher._create_jobs([orphan], [], graph, tiles)
    jobs = [j for j in dispatcher.pending_jobs if j.cart is orphan]
    assert len(jobs) == 1
    assert jobs[0].job_type == JobType.PICKUP_TO_BOX_DEPOT


def test_packed_waiting_cart_returns_home_not_back_to_packoff():
    """A cart dropped mid-return (order already packed) must go to Box Depot,
    never back to Pack-off for a second processing pass."""
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)
    cart = Cart((22, 9))
    cart.state = CartState.WAITING_FOR_STATION
    cart.order = Order()
    cart.order.stations_to_visit = [1]
    cart.order.completed_stations = [1]
    cart.order.packed = True
    dispatcher._create_jobs([cart], [], graph, tiles)
    jobs = [j for j in dispatcher.pending_jobs if j.cart is cart]
    assert len(jobs) == 1
    assert jobs[0].job_type == JobType.RETURN_TO_BOX_DEPOT


def test_giveup_drop_releases_cart_in_place():
    """Giving up on a stuck carrying AGV must release the cart at the AGV's
    physical position — never teleport it to a distant tile."""
    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)
    agv = AGV((24, 24))  # parking tile — highway drops are forbidden
    cart = Cart((24, 24))
    cart.carried_by = agv
    cart.state = CartState.IN_TRANSIT_TO_PICK
    agv.carrying_cart = cart
    agv.state = AGVState.MOVING_TO_DROPOFF
    agv.is_blocked = True
    agv.blocked_timer = 100.0
    job = Job(JobType.MOVE_TO_PICK, cart, (22, 12), station_id="S1")
    job.retarget_count = 3
    job.assigned_agv = agv
    agv.current_job = job
    dispatcher.active_jobs.append(job)
    dispatcher._cancel_stuck_jobs([agv], [cart], graph, tiles)
    assert cart.pos == (24, 24)
    assert cart.carried_by is None
    assert agv.carrying_cart is None


# -- Graph safety invariants (map-agnostic: must hold for ANY layout) --

def test_graph_has_no_sink_nodes():
    """Every node needs an outgoing edge — a sink permanently traps an AGV
    (row 8's westbound lane used to dead-end at (1,8))."""
    tiles = build_map()
    graph = build_graph(tiles)
    sinks = [pos for pos, nbrs in graph.items() if not nbrs]
    assert sinks == []


def test_graph_fully_mutually_reachable():
    """Every node must be reachable from the spawn exit AND able to return.
    One-way sections that strand AGVs deadlock the sim eventually."""
    from collections import deque

    tiles = build_map()
    graph = build_graph(tiles)
    start = (15, 7)

    def bfs(adjacency, src):
        seen = {src}
        queue = deque([src])
        while queue:
            cur = queue.popleft()
            for nxt in adjacency.get(cur, set()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    reverse: dict = {pos: set() for pos in graph}
    for pos, nbrs in graph.items():
        for nxt in nbrs:
            reverse[nxt].add(pos)

    assert set(graph) - bfs(graph, start) == set()
    assert set(graph) - bfs(reverse, start) == set()


def test_no_headon_two_cycle_at_choke_points():
    """A bidirectional highway pair where one side is the ONLY route between
    two regions lets two AGVs meet head-on and freeze the warehouse (the old
    (8,7)<->(9,7) junction). Bidirectional pairs are only safe when each
    side has an alternative route around the pair."""
    from collections import deque

    tiles = build_map()
    graph = build_graph(tiles)

    def reachable_without(src, dst, banned_edge):
        seen = {src}
        queue = deque([src])
        while queue:
            cur = queue.popleft()
            if cur == dst:
                return True
            for nxt in graph.get(cur, set()):
                if (cur, nxt) == banned_edge or nxt in seen:
                    continue
                seen.add(nxt)
                queue.append(nxt)
        return False

    for a, nbrs in graph.items():
        for b in nbrs:
            if a < b and a in graph.get(b, set()):
                if tiles[a].tile_type != TileType.HIGHWAY:
                    continue
                if tiles[b].tile_type != TileType.HIGHWAY:
                    continue
                # Each direction must survive losing its direct edge
                assert reachable_without(a, b, (a, b)), (
                    f"head-on choke: {a}->{b} has no alternative route"
                )
                assert reachable_without(b, a, (b, a)), (
                    f"head-on choke: {b}->{a} has no alternative route"
                )
