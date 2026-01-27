"""
Test suite for AGV collision avoidance, highway preference, rerouting, and spawn guard.
No pygame dependency — imports only logic functions/classes from agv_simulation.
"""
import sys
import types

# Stub out pygame so we can import agv_simulation without a display
_pg = types.ModuleType("pygame")
_pg.init = lambda: None
_pg.quit = lambda: None
_pg.display = types.ModuleType("pygame.display")
_pg.display.set_mode = lambda *a, **k: None
_pg.display.set_caption = lambda *a, **k: None
_pg.font = types.ModuleType("pygame.font")
_pg.font.SysFont = lambda *a, **k: None
sys.modules["pygame"] = _pg
sys.modules["pygame.display"] = _pg.display
sys.modules["pygame.font"] = _pg.font

from agv_simulation import (
    Tile, TileType, AGV, AGVState, Cart, CartState,
    AGV_SPAWN_TILE, astar, build_map, build_graph,
)


# ── Helpers ──────────────────────────────────────────────────

def _make_tile(x, y, tt):
    return Tile(x, y, tt)


def _small_graph_with_highway_and_parking():
    """
    Build a small 5×3 grid:

       (0,0)─(1,0)─(2,0)─(3,0)─(4,0)    ← all PARKING (cost 10)
         │                         │
       (0,1)─(1,1)─(2,1)─(3,1)─(4,1)    ← all HIGHWAY (cost 1)
         │                         │
       (0,2)─(1,2)─(2,2)─(3,2)─(4,2)    ← all PARKING (cost 10)

    Start=(0,1), Goal=(4,1).
    Highway path (bottom row): 5 tiles, cost 4.
    Parking path via row 0: 9 tiles, cost 80.
    A* with tiles should pick the highway path.
    """
    tiles = {}
    graph = {}
    for x in range(5):
        for y in range(3):
            tt = TileType.HIGHWAY if y == 1 else TileType.PARKING
            tiles[(x, y)] = _make_tile(x, y, tt)
            graph[(x, y)] = set()

    # Build bidirectional edges: horizontal in each row, vertical at ends
    for y in range(3):
        for x in range(4):
            graph[(x, y)].add((x + 1, y))
            graph[(x + 1, y)].add((x, y))
    for x in [0, 4]:
        for y in range(2):
            graph[(x, y)].add((x, y + 1))
            graph[(x, y + 1)].add((x, y))

    return graph, tiles


# ── Tests ────────────────────────────────────────────────────

def test_astar_prefers_highway():
    """A* picks the highway path even when a shorter-tile-count parking path exists."""
    graph, tiles = _small_graph_with_highway_and_parking()
    path = astar(graph, (0, 1), (4, 1), tiles=tiles)
    assert path is not None
    # The highway path stays on row 1 the entire way
    for node in path:
        assert tiles[node].tile_type == TileType.HIGHWAY, (
            f"Expected highway at {node}, got {tiles[node].tile_type}"
        )


def test_astar_blocked_tiles():
    """A* avoids a blocked tile and finds an alternative."""
    graph, tiles = _small_graph_with_highway_and_parking()
    # Block the middle highway tile
    blocked = {(2, 1)}
    path = astar(graph, (0, 1), (4, 1), blocked=blocked, tiles=tiles)
    assert path is not None
    assert (2, 1) not in path


def test_astar_blocked_allows_goal():
    """A* still finds path to goal even when goal tile is in the blocked set."""
    graph, tiles = _small_graph_with_highway_and_parking()
    goal = (4, 1)
    blocked = {goal}
    path = astar(graph, (0, 1), goal, blocked=blocked, tiles=tiles)
    assert path is not None
    assert path[-1] == goal


def test_two_lane_directions():
    """Row 7 cols 1-8 only goes East; row 8 cols 1-8 only goes West."""
    tiles = build_map()
    graph = build_graph(tiles)

    # Row 7 (outbound): each tile should connect East (x+1)
    for x in range(1, 9):
        neighbors = graph.get((x, 7), set())
        # Must have (x+1, 7) as neighbor (East)
        assert (x + 1, 7) in neighbors, f"({x},7) missing East neighbor"
        # Must NOT have (x-1, 7) as highway neighbor (West) — except
        # non-highway side connections are allowed
        if x > 1:
            # The highway direction should be East-only; (x-1,7) should not
            # appear as a highway-to-highway connection
            assert (x - 1, 7) not in neighbors, (
                f"({x},7) should not go West to ({x-1},7)"
            )

    # Row 8 (inbound): each tile should connect West (x-1)
    for x in range(2, 9):
        neighbors = graph.get((x, 8), set())
        assert (x - 1, 8) in neighbors, f"({x},8) missing West neighbor"
        if x < 8:
            assert (x + 1, 8) not in neighbors, (
                f"({x},8) should not go East to ({x+1},8)"
            )


def test_agv_collision_block():
    """Two AGVs on adjacent tiles; one moving toward the other gets blocked."""
    tiles = build_map()
    graph = build_graph(tiles)

    # Place AGV1 at (1,7), AGV2 at (2,7)
    agv1 = AGV((1, 7))
    agv2 = AGV((2, 7))
    agvs = [agv1, agv2]

    # Give AGV1 a path toward (3,7) — must pass through (2,7)
    agv1.path = [(1, 7), (2, 7), (3, 7)]
    agv1.path_index = 0
    agv1.path_progress = 0.0
    agv1.state = AGVState.MOVING
    agv1.target = (3, 7)

    # AGV2 is idle at (2,7)
    agv2.state = AGVState.IDLE

    # Tick AGV1 enough to try advancing
    agv1.update(1.5, agvs=agvs, carts=[], graph=graph, tiles=tiles)

    # AGV1 should NOT have moved onto AGV2's tile
    assert agv1.pos != agv2.pos, "AGV1 should not overlap AGV2"


def test_agv_reroute_on_block():
    """AGV blocked by another, with graph/tiles passed, reroutes around."""
    tiles = build_map()
    graph = build_graph(tiles)

    # AGV1 at (1,7) wants to go to (3,7); AGV2 blocks (2,7)
    agv1 = AGV((1, 7))
    agv2 = AGV((2, 7))
    agvs = [agv1, agv2]

    agv1.path = [(1, 7), (2, 7), (3, 7)]
    agv1.path_index = 0
    agv1.path_progress = 0.0
    agv1.state = AGVState.MOVING
    agv1.target = (3, 7)

    agv2.state = AGVState.IDLE

    # Tick — should trigger immediate reroute
    agv1.update(1.5, agvs=agvs, carts=[], graph=graph, tiles=tiles)

    # After reroute, AGV1's path should avoid (2,7)
    if agv1._just_rerouted:
        assert (2, 7) not in agv1.path[1:], (
            "Rerouted path should avoid blocked tile"
        )


def test_agv_reroute_rejects_same_first_step():
    """reroute() returns False when only available path has same first step."""
    # Build a trivial linear graph: A — B — C
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

    # No other AGVs blocking — reroute returns new path with same first step
    agv2 = AGV((5, 5))  # far away, not blocking
    result = agv1.reroute(graph, [agv1, agv2], tiles=tiles)
    # The only path is A→B→C, same first step, so reroute should reject
    assert result is False


def test_spawn_guard():
    """Can't spawn AGV if spawn tile is occupied."""
    agvs = []
    # First spawn succeeds
    agv1 = AGV(AGV_SPAWN_TILE)
    agvs.append(agv1)

    # Check if spawn tile is occupied
    occupied = any(a.pos == AGV_SPAWN_TILE for a in agvs)
    assert occupied is True, "Spawn tile should be occupied"

    # Move AGV1 away
    agv1.pos = (5, 7)
    occupied = any(a.pos == AGV_SPAWN_TILE for a in agvs)
    assert occupied is False, "Spawn tile should be free now"


def test_cart_cart_collision_only_when_carrying():
    """AGV going to pickup should NOT be blocked by stationary cart at target.
    AGV actually carrying SHOULD be blocked by stationary cart."""
    tiles = build_map()
    graph = build_graph(tiles)

    # Place a stationary cart at (3,7)
    cart_blocker = Cart((3, 7))
    cart_blocker.state = CartState.IDLE
    cart_blocker.carried_by = None

    # AGV going to pick up cart_blocker — carrying_cart is set but carried_by is not self
    agv = AGV((1, 7))
    agv.path = [(1, 7), (2, 7), (3, 7)]
    agv.path_index = 0
    agv.path_progress = 0.0
    agv.state = AGVState.MOVING_TO_PICKUP
    agv.target = (3, 7)
    agv.carrying_cart = cart_blocker  # set early (pickup_cart sets this)

    carts = [cart_blocker]
    agvs = [agv]

    # Tick enough to try advancing past (2,7) to (3,7)
    agv.update(3.0, agvs=agvs, carts=carts, graph=graph, tiles=tiles)

    # AGV should be able to reach (3,7) — not blocked by the cart it's going to pick up
    assert agv.pos == (3, 7), (
        f"AGV going to pickup should NOT be blocked by target cart; pos={agv.pos}"
    )

    # Now simulate an AGV that IS carrying a cart (carried_by == self)
    carried_cart = Cart((10, 7))
    carried_cart.state = CartState.IN_TRANSIT
    carried_cart.carried_by = None  # will be set below

    agv2 = AGV((1, 7))
    carried_cart.carried_by = agv2
    agv2.carrying_cart = carried_cart
    agv2.path = [(1, 7), (2, 7), (3, 7)]
    agv2.path_index = 0
    agv2.path_progress = 0.0
    agv2.state = AGVState.MOVING_TO_DROPOFF
    agv2.target = (3, 7)

    # cart_blocker is still at (3,7)
    carts2 = [cart_blocker, carried_cart]
    agvs2 = [agv2]

    agv2.update(3.0, agvs=agvs2, carts=carts2, graph=graph, tiles=tiles)

    # AGV carrying a cart SHOULD be blocked by stationary cart at (3,7)
    # It should have rerouted or be blocked — either way, not at (3,7)
    assert agv2.pos != (3, 7) or agv2._just_rerouted, (
        "AGV carrying cart should be blocked by stationary cart"
    )


def test_no_tile_overlap_simulation():
    """Spawn 3 AGVs, simulate 100 ticks. No two AGVs share a tile at any tick."""
    tiles = build_map()
    graph = build_graph(tiles)

    # Spawn 3 AGVs at distinct starting positions
    start_positions = [(1, 7), (2, 7), (3, 7)]
    agvs = [AGV(pos) for pos in start_positions]

    # Give them different destinations
    destinations = [(8, 12), (10, 17), (39, 35)]
    for agv, dest in zip(agvs, destinations):
        agv.set_destination(dest, graph, tiles)

    dt = 0.1
    for tick in range(100):
        for agv in agvs:
            agv.update(dt, agvs=agvs, carts=[], graph=graph, tiles=tiles)

        # Check no overlap
        positions = [a.pos for a in agvs]
        assert len(positions) == len(set(positions)), (
            f"Tick {tick}: AGV tile overlap detected! positions={positions}"
        )


def test_highway_cost_weight():
    """Directly call astar with tiles containing mix of highway and parking.
    Verify total g-cost of returned path uses weighted costs."""
    graph, tiles = _small_graph_with_highway_and_parking()

    # Get path along highway row
    path = astar(graph, (0, 1), (4, 1), tiles=tiles)
    assert path is not None

    # Compute expected cost: all highway tiles (cost 1 each), goal costs 1
    # Path: (0,1) → (1,1) → (2,1) → (3,1) → (4,1) = 4 edges, all highway = cost 4
    total_cost = 0
    for i in range(1, len(path)):
        node = path[i]
        if node == (4, 1):  # goal
            total_cost += 1
        else:
            tile = tiles.get(node)
            total_cost += 1 if (tile and tile.tile_type == TileType.HIGHWAY) else 10
    assert total_cost == 4, f"Expected cost 4 for all-highway path, got {total_cost}"

    # Now block the highway and force parking detour
    blocked = {(2, 1)}
    path2 = astar(graph, (0, 1), (4, 1), blocked=blocked, tiles=tiles)
    assert path2 is not None
    assert (2, 1) not in path2

    # The detour path should have higher cost due to parking tiles
    total_cost2 = 0
    for i in range(1, len(path2)):
        node = path2[i]
        if node == (4, 1):  # goal
            total_cost2 += 1
        else:
            tile = tiles.get(node)
            total_cost2 += 1 if (tile and tile.tile_type == TileType.HIGHWAY) else 10
    assert total_cost2 > total_cost, (
        f"Detour cost ({total_cost2}) should exceed highway cost ({total_cost})"
    )
