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

    # 1. AGV SPAWN (top-left, cols 1-8, rows 0-6)
    fill_rect(1, 0, 8, 6, TileType.AGV_SPAWN)

    # 2. CART SPAWN (left edge, row 7 only)
    put(0, 7, TileType.CART_SPAWN)

    # 3. BOX DEPOT (top-centre)
    fill_rect(14, 1, 24, 4, TileType.BOX_DEPOT, "Box_Depot")
    for i in range(8):
        put(15 + i, 5, TileType.PARKING, "Box_Depot")
    for i in range(8):
        put(15 + i, 6, TileType.HIGHWAY)

    # 4. PACK-OFF CONVEYOR (top-right)
    fill_rect(47, 1, 54, 3, TileType.PACKOFF, "Pack_off")
    for i in range(4):
        put(49 + i, 4, TileType.PARKING, "Pack_off")
    for i in range(4):
        vline(49 + i, 5, 6, TileType.HIGHWAY)

    # 5. NORTH HIGHWAY (row 7, full width)
    hline(1, 57, NORTH_HWY_ROW, TileType.HIGHWAY)
    hline(1, 8, NORTH_HWY_ROW + 1, TileType.HIGHWAY)
    hline(39, 57, NORTH_HWY_ROW + 1, TileType.HIGHWAY)

    # 6. LEFT SECTION – single highway at col 9
    vline(LEFT_HWY_COL, 8, EAST_HWY_ROW, TileType.HIGHWAY)

    # 7. EAST HIGHWAY (row 38)
    hline(LEFT_HWY_COL, RIGHT_HWY_COL, EAST_HWY_ROW, TileType.HIGHWAY)

    # 8. RIGHT SECTION – single highway at col 38
    vline(RIGHT_HWY_COL, 8, EAST_HWY_ROW, TileType.HIGHWAY)

    # 10. LEFT-SIDE STATIONS
    # S1
    fill_rect(4, 10, 7, 14, TileType.RACKING, "S1")
    for y in range(10, 15):
        put(8, y, TileType.PICK_STATION, "S1")
    # S2
    fill_rect(11, 17, 16, 20, TileType.RACKING, "S2")
    for y in range(17, 21):
        put(10, y, TileType.PICK_STATION, "S2")
    # S3
    fill_rect(4, 23, 7, 26, TileType.RACKING, "S3")
    for y in range(23, 27):
        put(8, y, TileType.PICK_STATION, "S3")
    # S4
    fill_rect(11, 29, 16, 32, TileType.RACKING, "S4")
    for y in range(29, 33):
        put(10, y, TileType.PICK_STATION, "S4")

    # 11. RIGHT-SIDE STATIONS
    # S5
    fill_rect(40, 34, 44, 36, TileType.RACKING, "S5")
    for y in range(34, 37):
        put(39, y, TileType.PICK_STATION, "S5")
    # S6
    fill_rect(32, 28, 36, 31, TileType.RACKING, "S6")
    for y in range(28, 32):
        put(37, y, TileType.PICK_STATION, "S6")
    # S7
    fill_rect(40, 22, 44, 25, TileType.RACKING, "S7")
    for y in range(22, 26):
        put(39, y, TileType.PICK_STATION, "S7")
    # S8
    fill_rect(32, 16, 36, 19, TileType.RACKING, "S8")
    for y in range(16, 20):
        put(37, y, TileType.PICK_STATION, "S8")

    # 12. S9
    fill_rect(40, 10, 44, 13, TileType.RACKING, "S9")
    for y in range(10, 14):
        put(39, y, TileType.PICK_STATION, "S9")

    # 13. PARKING – opposite side of each station
    for y in range(10, 15):
        put(10, y, TileType.PARKING)
    for y in range(17, 21):
        put(8, y, TileType.PARKING)
    for y in range(23, 27):
        put(10, y, TileType.PARKING)
    for y in range(29, 33):
        put(8, y, TileType.PARKING)

    for y in range(34, 37):
        put(37, y, TileType.PARKING)
    for y in range(28, 32):
        put(39, y, TileType.PARKING)
    for y in range(22, 26):
        put(37, y, TileType.PARKING)
    for y in range(16, 20):
        put(39, y, TileType.PARKING)
    for y in range(10, 14):
        put(37, y, TileType.PARKING)

    # Gap rows: parking on both sides of highway
    left_gap_rows = [9, 15, 16, 21, 22, 27, 28, 33, 34, 35, 36, 37]
    for y in left_gap_rows:
        for x in (8, 10):
            if (x, y) not in tiles:
                put(x, y, TileType.PARKING)

    right_gap_rows = [9, 14, 15, 20, 21, 26, 27, 32, 33, 37]
    for y in right_gap_rows:
        for x in (37, 39):
            if (x, y) not in tiles:
                put(x, y, TileType.PARKING)

    # Along North Highway (one row above, row 6)
    for x in [10, 12, 26, 28, 30, 40, 55]:
        if (x, 6) not in tiles:
            put(x, 6, TileType.PARKING)

    # Along East Highway (one row below, row 39)
    for x in [12, 18, 24, 30, 36]:
        put(x, 39, TileType.PARKING)

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

    # Junction special cases
    junctions: dict[tuple[int, int], list[tuple[int, int]]] = {
        (9, 7):   [(0, 1), (-1, 0)],
        (9, 8):   [(0, 1), (-1, 0)],
        (9, 38):  [(1, 0)],
        (38, 38): [(0, -1)],
        (38, 8):  [(0, -1), (1, 0)],
        (38, 7):  [(-1, 0)],
        (57, 8):  [(0, -1)],
    }

    def get_highway_directions(x: int, y: int) -> list[tuple[int, int]]:
        """Return list of ``(dx, dy)`` allowed moves for a highway tile."""
        if (x, y) in junctions:
            return junctions[(x, y)]
        if y == 7 and 1 <= x <= 8:
            return [(1, 0)]
        if y == 8 and 1 <= x <= 8:
            return [(-1, 0)]
        if y == 7 and 10 <= x <= 57:
            dirs = [(-1, 0)]
            if 15 <= x <= 22:
                dirs.append((0, -1))
            if 49 <= x <= 52:
                dirs.append((0, -1))
            return dirs
        if x == 9 and 8 <= y <= 38:
            return [(0, 1)]
        if y == 38 and 9 <= x <= 38:
            return [(1, 0)]
        if x == 38 and 8 <= y <= 38:
            return [(0, -1)]
        if y == 8 and 39 <= x <= 57:
            return [(1, 0)]
        if 15 <= x <= 22 and 5 <= y <= 6:
            return [(0, -1), (0, 1)]
        if 49 <= x <= 52 and 5 <= y <= 6:
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
        ("Spawn → S1 pick (8,12)", AGV_SPAWN_TILE, (8, 12)),
        ("Spawn → S5 pick (39,35)", AGV_SPAWN_TILE, (39, 35)),
        ("S1 pick (8,12) → Spawn (return)", (8, 12), AGV_SPAWN_TILE),
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
