"""Map and graph builders for the warehouse layout."""

from __future__ import annotations

import logging

from .enums import TileType
from .constants import (
    AGV_SPAWN_TILE, TILE_TRAVEL_TIME,
    LEFT_HWY_COL, RIGHT_HWY_COL, NORTH_HWY_ROW, EAST_HWY_ROW,
)
from .models import Tile
from .pathfinding import astar
from .aisles import aisle_rack_positions

logger = logging.getLogger(__name__)


def build_map() -> dict[tuple[int, int], Tile]:
    """Create the full warehouse map. Returns ``{(x, y): Tile, ...}``."""
    tiles: dict[tuple[int, int], Tile] = {}

    def put(x: int, y: int, tt: TileType, sid: str | None = None) -> None:
        tiles[(x, y)] = Tile(x, y, tt, sid)

    def fill_rect(
        x1: int, y1: int, x2: int, y2: int,
        tt: TileType, sid: str | None = None,
    ) -> None:
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                put(x, y, tt, sid)

    def hline(x1: int, x2: int, y: int, tt: TileType, sid: str | None = None) -> None:
        for x in range(x1, x2 + 1):
            put(x, y, tt, sid)

    def vline(x: int, y1: int, y2: int, tt: TileType, sid: str | None = None) -> None:
        for y in range(y1, y2 + 1):
            put(x, y, tt, sid)

    # NOTE: all coordinates are shifted +14 columns vs the original 60-col
    # layout (cols 0-13 are reserved for the west aisle bank, 74-85 east).

    # 1. AGV SPAWN (top-left, cols 15-22, rows 0-6)
    fill_rect(15, 0, 22, 6, TileType.AGV_SPAWN)

    # 2. CART SPAWN (left edge of legacy area, row 7 only)
    # (14,7) was the legacy cart spawn; carts now enter at the Box Depot.
    put(14, 7, TileType.PARKING)

    # 3. BOX DEPOT (top-centre)
    fill_rect(28, 1, 38, 4, TileType.BOX_DEPOT, "Box_Depot")
    for i in range(8):
        put(29 + i, 5, TileType.PARKING, "Box_Depot")
    for i in range(8):
        put(29 + i, 6, TileType.HIGHWAY)

    # 4. PACK-OFF CONVEYOR (top-right)
    fill_rect(61, 1, 68, 3, TileType.PACKOFF, "Pack_off")
    for i in range(4):
        put(63 + i, 4, TileType.PARKING, "Pack_off")
    for i in range(4):
        vline(63 + i, 5, 6, TileType.HIGHWAY)

    # 5. NORTH HIGHWAY (row 7, full width)
    hline(15, 71, NORTH_HWY_ROW, TileType.HIGHWAY)
    hline(15, 22, NORTH_HWY_ROW + 1, TileType.HIGHWAY)
    hline(53, 71, NORTH_HWY_ROW + 1, TileType.HIGHWAY)

    # 6. LEFT SECTION – single highway at col 9
    vline(LEFT_HWY_COL, 8, EAST_HWY_ROW, TileType.HIGHWAY)

    # 7. EAST HIGHWAY (row 38)
    hline(LEFT_HWY_COL, RIGHT_HWY_COL, EAST_HWY_ROW, TileType.HIGHWAY)

    # 8. RIGHT SECTION – single highway at col 38
    vline(RIGHT_HWY_COL, 8, EAST_HWY_ROW, TileType.HIGHWAY)

    # 10. LEFT-SIDE STATIONS
    # S1
    fill_rect(18, 10, 21, 14, TileType.RACKING, "S1")
    for y in range(10, 15):
        put(22, y, TileType.PICK_STATION, "S1")
    # S2
    fill_rect(25, 17, 30, 20, TileType.RACKING, "S2")
    for y in range(17, 21):
        put(24, y, TileType.PICK_STATION, "S2")
    # S3
    fill_rect(18, 23, 21, 26, TileType.RACKING, "S3")
    for y in range(23, 27):
        put(22, y, TileType.PICK_STATION, "S3")
    # S4
    fill_rect(25, 29, 30, 32, TileType.RACKING, "S4")
    for y in range(29, 33):
        put(24, y, TileType.PICK_STATION, "S4")

    # 11. RIGHT-SIDE STATIONS
    # S5
    fill_rect(54, 34, 58, 36, TileType.RACKING, "S5")
    for y in range(34, 37):
        put(53, y, TileType.PICK_STATION, "S5")
    # S6
    fill_rect(46, 28, 50, 31, TileType.RACKING, "S6")
    for y in range(28, 32):
        put(51, y, TileType.PICK_STATION, "S6")
    # S7
    fill_rect(54, 22, 58, 25, TileType.RACKING, "S7")
    for y in range(22, 26):
        put(53, y, TileType.PICK_STATION, "S7")
    # S8
    fill_rect(46, 16, 50, 19, TileType.RACKING, "S8")
    for y in range(16, 20):
        put(51, y, TileType.PICK_STATION, "S8")

    # 12. S9
    fill_rect(54, 10, 58, 13, TileType.RACKING, "S9")
    for y in range(10, 14):
        put(53, y, TileType.PICK_STATION, "S9")

    # 13. PARKING – opposite side of each station
    for y in range(10, 15):
        put(24, y, TileType.PARKING)
    for y in range(17, 21):
        put(22, y, TileType.PARKING)
    for y in range(23, 27):
        put(24, y, TileType.PARKING)
    for y in range(29, 33):
        put(22, y, TileType.PARKING)

    for y in range(34, 37):
        put(51, y, TileType.PARKING)
    for y in range(28, 32):
        put(53, y, TileType.PARKING)
    for y in range(22, 26):
        put(51, y, TileType.PARKING)
    for y in range(16, 20):
        put(53, y, TileType.PARKING)
    for y in range(10, 14):
        put(51, y, TileType.PARKING)

    # Gap rows: parking on both sides of highway
    left_gap_rows = [9, 15, 16, 21, 22, 27, 28, 33, 34, 35, 36, 37]
    for y in left_gap_rows:
        for x in (22, 24):
            if (x, y) not in tiles:
                put(x, y, TileType.PARKING)

    right_gap_rows = [9, 14, 15, 20, 21, 26, 27, 32, 33, 37]
    for y in right_gap_rows:
        for x in (51, 53):
            if (x, y) not in tiles:
                put(x, y, TileType.PARKING)

    # Along North Highway (one row above, row 6)
    for x in [24, 26, 40, 42, 44, 54, 69]:
        if (x, 6) not in tiles:
            put(x, 6, TileType.PARKING)

    # Along East Highway (one row below, row 39)
    for x in [26, 32, 38, 44, 50]:
        put(x, 39, TileType.PARKING)

    # 14. PRODUCT AISLES — three banks of bi-level pick racking (PRD §14).
    # Not walkable by AGVs; pickers-only territory.
    for (x, y) in aisle_rack_positions():
        put(x, y, TileType.AISLE_RACK)

    return tiles


def build_graph(
    tiles: dict[tuple[int, int], Tile],
) -> dict[tuple[int, int], set[tuple[int, int]]]:
    """Build a directed adjacency dict from the tile map.

    Encodes the anti-clockwise one-way loop for highway tiles, plus
    bidirectional access to/from stations and parking.
    """
    graph: dict[tuple[int, int], set[tuple[int, int]]] = {}

    highway_positions: set[tuple[int, int]] = set()
    non_highway_positions: set[tuple[int, int]] = set()
    for pos, tile in tiles.items():
        if tile.tile_type == TileType.HIGHWAY:
            highway_positions.add(pos)
        elif tile.tile_type in (
            TileType.PICK_STATION, TileType.PARKING,
            TileType.AGV_SPAWN, TileType.CART_SPAWN,
        ):
            non_highway_positions.add(pos)

    all_positions = highway_positions | non_highway_positions

    for pos in all_positions:
        graph[pos] = set()

    # Junction special cases (coords shifted +14 with the grid expansion)
    junctions: dict[tuple[int, int], list[tuple[int, int]]] = {
        # (23,7) must NOT flow west into (22,7): row 7 cols 15-22 flows east
        # into (23,7), so a westbound edge creates a head-on deadlock 2-cycle
        # at the only connector between the NW corridor and the loop. Spawn-
        # area access is via (23,8) → row 8 → merge north instead.
        (23, 7):  [(0, 1)],
        (23, 8):  [(0, 1), (-1, 0)],
        (23, 38): [(1, 0)],
        (52, 38): [(0, -1)],
        (52, 8):  [(0, -1), (1, 0)],
        (52, 7):  [(-1, 0)],
        (71, 8):  [(0, -1)],
    }

    def get_highway_directions(x: int, y: int) -> list[tuple[int, int]]:
        """Return list of ``(dx, dy)`` allowed moves for a highway tile."""
        if (x, y) in junctions:
            return junctions[(x, y)]
        if y == 7 and 15 <= x <= 22:
            return [(1, 0)]
        if y == 8 and 15 <= x <= 22:
            # Westbound return lane may merge north into the eastbound lane
            # (and from there sidetrack into the spawn area). Without the
            # merge, (15,8) is a dead-end trap with no outgoing edges.
            return [(-1, 0), (0, -1)]
        if y == 7 and 24 <= x <= 71:
            dirs = [(-1, 0)]
            if 29 <= x <= 36:
                dirs.append((0, -1))
            if 63 <= x <= 66:
                dirs.append((0, -1))
            return dirs
        if x == 23 and 8 <= y <= 38:
            return [(0, 1)]
        if y == 38 and 23 <= x <= 52:
            return [(1, 0)]
        if x == 52 and 8 <= y <= 38:
            return [(0, -1)]
        if y == 8 and 53 <= x <= 71:
            return [(1, 0)]
        if 29 <= x <= 36 and 5 <= y <= 6:
            return [(0, -1), (0, 1)]
        if 63 <= x <= 66 and 5 <= y <= 6:
            return [(0, -1), (0, 1)]
        return []

    # Build highway edges
    for pos in highway_positions:
        x, y = pos
        for dx, dy in get_highway_directions(x, y):
            neighbor = (x + dx, y + dy)
            if neighbor in all_positions:
                graph[pos].add(neighbor)

    # Non-highway tiles: all 4 cardinal directions
    for pos in non_highway_positions:
        x, y = pos
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            neighbor = (x + dx, y + dy)
            if neighbor in all_positions:
                graph[pos].add(neighbor)

    # Sidetrack edges: highway ↔ adjacent non-highway
    for pos in highway_positions:
        x, y = pos
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            neighbor = (x + dx, y + dy)
            if neighbor in non_highway_positions:
                tile = tiles[neighbor]
                if tile.tile_type in (
                    TileType.PICK_STATION, TileType.PARKING,
                    TileType.AGV_SPAWN, TileType.CART_SPAWN,
                ):
                    graph[pos].add(neighbor)
                    graph[neighbor].add(pos)

    return graph


def verify_graph(
    graph: dict[tuple[int, int], set[tuple[int, int]]],
    tiles: dict[tuple[int, int], Tile],
) -> None:
    """Log graph stats and test a few key paths at startup."""
    logger.info("--- Graph verification ---")
    logger.info("Graph nodes: %d", len(graph))
    total_edges = sum(len(v) for v in graph.values())
    logger.info("Graph edges: %d", total_edges)

    tests = [
        ("Spawn → S1 pick (22,12)", AGV_SPAWN_TILE, (22, 12)),
        ("Spawn → S5 pick (53,35)", AGV_SPAWN_TILE, (53, 35)),
        ("S1 pick (22,12) → Spawn (return)", (22, 12), AGV_SPAWN_TILE),
    ]
    for desc, start, goal in tests:
        path = astar(graph, start, goal, tiles=tiles)
        if path:
            logger.info(
                "  %s: %d tiles, ~%.0fs",
                desc, len(path), len(path) * TILE_TRAVEL_TIME,
            )
        else:
            logger.info("  %s: NO PATH FOUND!", desc)
    logger.info("--- End verification ---")
