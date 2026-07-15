"""Dynamic highway layout: movable pillars and everything riding on them.

Covers: bound validation and clamped moves, default-layout equivalence with
the classic fixed map, full world validity at moved layouts (stations placed,
loop routable both ways, all 9 zones populated, 2000 SKUs conserved), the
product redistribution that follows an aisle-length change, per-station
longest-walk stats, and a headless smoke run on a moved layout.
"""

import pytest

from agv_simulation.aisles import init_catalog
from agv_simulation.constants import AGV_SPAWN_TILE, NUM_SKUS
from agv_simulation.enums import TileType
from agv_simulation.layout import (
    LEFT_COL_MIN, MIN_PILLAR_GAP, RIGHT_COL_MAX,
    HighwayLayout, get_layout, set_layout,
)
from agv_simulation.map_builder import build_graph, build_map
from agv_simulation.pathfinding import astar

# Representative moved layouts: both pillars left, both right, maximum
# spread, and minimum central gap.
MOVED_LAYOUTS = [(18, 60), (30, 64), (16, 70), (20, 37)]


@pytest.fixture(autouse=True)
def _restore_default_layout():
    """Every test leaves the module singleton back at the classic layout."""
    set_layout(HighwayLayout())
    yield
    set_layout(HighwayLayout())


def _build_world(left, right):
    set_layout(HighwayLayout(left, right))
    tiles = build_map()
    graph = build_graph(tiles)
    return tiles, graph


# ----------------------------------------------------------------------
# Bounds and clamping
# ----------------------------------------------------------------------

def test_default_layout_is_classic():
    lay = HighwayLayout()
    assert (lay.left_col, lay.right_col) == (23, 52)
    banks = {b.name: (b.col_start, b.col_end) for b in lay.banks}
    assert banks == {"west": (0, 12), "central": (31, 45), "east": (60, 84)}


@pytest.mark.parametrize("left,right", [
    (LEFT_COL_MIN - 1, 52),           # left pillar too far left
    (23, RIGHT_COL_MAX + 1),          # right pillar too far right
    (23, 23 + MIN_PILLAR_GAP - 1),    # central gap too small
])
def test_invalid_layouts_rejected(left, right):
    with pytest.raises(ValueError):
        HighwayLayout(left, right)


def test_move_pillar_clamps():
    lay = HighwayLayout()
    assert lay.move_pillar("left", 0).left_col == LEFT_COL_MIN
    assert lay.move_pillar("left", 50).left_col == 52 - MIN_PILLAR_GAP
    assert lay.move_pillar("right", 85).right_col == RIGHT_COL_MAX
    assert lay.move_pillar("right", 20).right_col == 23 + MIN_PILLAR_GAP
    assert lay.move_pillar("left", 20) == HighwayLayout(20, 52)


# ----------------------------------------------------------------------
# Default layout reproduces the classic map
# ----------------------------------------------------------------------

def test_default_map_marker_tiles():
    tiles = build_map()
    assert tiles[(22, 12)].tile_type == TileType.PICK_STATION
    assert tiles[(22, 12)].station_id == "S1"
    assert tiles[(53, 35)].tile_type == TileType.PICK_STATION
    assert tiles[(53, 35)].station_id == "S5"
    assert tiles[(23, 20)].tile_type == TileType.HIGHWAY   # left pillar
    assert tiles[(52, 20)].tile_type == TileType.HIGHWAY   # right pillar
    assert tiles[(18, 10)].station_id == "S1"              # racking block
    assert tiles[(46, 16)].station_id == "S8"


# ----------------------------------------------------------------------
# Moved layouts: full world validity
# ----------------------------------------------------------------------

@pytest.mark.parametrize("left,right", MOVED_LAYOUTS)
def test_moved_layout_stations_and_routing(left, right):
    tiles, graph = _build_world(left, right)
    lay = get_layout()

    for spec in lay.stations:
        mid_row = (spec.y0 + spec.y1) // 2
        pick = (spec.station_col, mid_row)
        tile = tiles[pick]
        assert tile.tile_type == TileType.PICK_STATION
        assert tile.station_id == spec.sid
        # The one-way loop must reach every station and return
        assert astar(graph, AGV_SPAWN_TILE, pick, tiles=tiles), (
            f"{spec.sid}: no path spawn -> {pick} (L={left}, R={right})"
        )
        assert astar(graph, pick, AGV_SPAWN_TILE, tiles=tiles), (
            f"{spec.sid}: no return path {pick} -> spawn (L={left}, R={right})"
        )

    # No dead ends anywhere in the directed graph
    dead = [pos for pos, nbrs in graph.items() if not nbrs]
    assert not dead, f"dead-end graph nodes at L={left}, R={right}: {dead}"


@pytest.mark.parametrize("left,right", MOVED_LAYOUTS)
def test_moved_layout_catalog_zones(left, right):
    tiles, _graph = _build_world(left, right)
    cat = init_catalog(tiles)

    assert len(cat.slots) == NUM_SKUS
    assert sum(len(v) for v in cat.station_skus.values()) == NUM_SKUS
    for sid, skus in cat.station_skus.items():
        assert skus, f"{sid} owns no SKUs at L={left}, R={right}"

    longest = cat.longest_walk_m()
    assert set(longest) == set(cat.station_skus)
    assert all(d > 0 for d in longest.values())

    # Popularity-weighted mean pick-cycle time per station (map label):
    # positive, below the station's own worst case, plausible magnitude
    # (whole-catalog calibration is mean 30 s)
    avg = cat.station_avg_walk_s()
    assert set(avg) == set(cat.station_skus)
    from agv_simulation.aisles import walk_time_seconds
    for sid, v in avg.items():
        assert 0 < v <= walk_time_seconds(longest[sid])
        assert 5.0 < v < 120.0


def test_products_follow_aisle_length():
    """Moving the left pillar west shrinks the west bank and grows the
    central bank — the SKU spread follows the new aisle lengths."""
    def side_counts(left, right):
        tiles, _ = _build_world(left, right)
        cat = init_catalog(tiles)
        counts = {"west": 0, "central": 0, "east": 0}
        for slot in cat.slots.values():
            counts[slot.bank] += 1
        return counts

    base = side_counts(23, 52)
    moved = side_counts(18, 52)   # left pillar 5 columns west
    assert moved["west"] < base["west"]
    assert moved["central"] > base["central"]
    assert sum(moved.values()) == sum(base.values()) == NUM_SKUS


def test_longest_walk_tracks_layout():
    tiles, _ = _build_world(23, 52)
    cat = init_catalog(tiles)
    base, base_avg = cat.longest_walk_m(), cat.station_avg_walk_s()
    tiles, _ = _build_world(18, 60)
    cat = init_catalog(tiles)
    moved, moved_avg = cat.longest_walk_m(), cat.station_avg_walk_s()
    assert base != moved
    assert base_avg != moved_avg


# ----------------------------------------------------------------------
# Extra-slot strategy: +1 pick slot per station
# ----------------------------------------------------------------------

def test_extra_slots_layout():
    set_layout(HighwayLayout(extra_slots=True))
    tiles = build_map()
    graph = build_graph(tiles)
    lay = get_layout()
    base = HighwayLayout()
    for spec in lay.stations:
        extra = (spec.station_col, spec.extra_row)
        tile = tiles[extra]
        assert tile.tile_type == TileType.PICK_STATION
        assert tile.station_id == spec.sid
        # S5's extra slot sits ABOVE its column; everyone else's below
        if spec.sid == "S5":
            assert spec.extra_row == spec.y0 - 1
        else:
            assert spec.extra_row == spec.y1 + 1
        # Reachable both ways on the one-way loop
        assert astar(graph, AGV_SPAWN_TILE, extra, tiles=tiles)
        assert astar(graph, extra, AGV_SPAWN_TILE, tiles=tiles)

    # Capacity follows the live tiles: every S station gains exactly 1
    from agv_simulation.dispatcher import Dispatcher
    fill = Dispatcher(tiles).get_station_fill([])
    set_layout(base)
    base_fill = Dispatcher(build_map()).get_station_fill([])
    for sid in (f"S{i}" for i in range(1, 10)):
        assert fill[sid][1] == base_fill[sid][1] + 1

    # Zoning still sound with the shifted station centroids
    set_layout(HighwayLayout(extra_slots=True))
    cat = init_catalog(build_map())
    assert sum(len(v) for v in cat.station_skus.values()) == NUM_SKUS


def test_move_pillar_preserves_extra_slots():
    lay = HighwayLayout(extra_slots=True)
    assert lay.move_pillar("left", 20).extra_slots is True
    assert lay.move_pillar("right", 60).extra_slots is True


# ----------------------------------------------------------------------
# Headless smoke on a moved layout
# ----------------------------------------------------------------------

def test_headless_smoke_moved_layout():
    from agv_simulation import run_headless
    result = run_headless(
        num_agvs=6, num_carts=10, sim_duration=1200.0, tick_dt=0.1,
        seed=42, export=False, order_book=False, highway=(20, 60),
        snapshot_interval=0.0, log_level="WARNING",
    )
    assert result["highway"] == (20, 60)
    assert result["stuck_report"]["teleport_events"] == 0
    assert result["picker_stats"]["picks_done"] > 0
    # run_headless resets the singleton per call; default restored next run
    result2 = run_headless(
        num_agvs=2, num_carts=2, sim_duration=10.0, tick_dt=0.1,
        seed=42, export=False, order_book=False,
        snapshot_interval=0.0, log_level="WARNING",
    )
    assert result2["highway"] == (23, 52)
