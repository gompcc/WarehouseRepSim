"""Map and graph builders for the warehouse layout."""

from __future__ import annotations

import logging

from .enums import TileType
from .constants import (
    AGV_SPAWN_TILE, TILE_TRAVEL_TIME,
    NORTH_HWY_ROW, EAST_HWY_ROW,
)
from .layout import HighwayLayout, get_layout
from .models import Tile
from .pathfinding import astar
from .aisles import aisle_rack_positions

logger = logging.getLogger(__name__)


def build_map(
    layout: HighwayLayout | None = None,
) -> dict[tuple[int, int], Tile]:
    """Create the full warehouse map. Returns ``{(x, y): Tile, ...}``.

    Geometry attached to the highway pillars (stations, station racking,
    parking, aisle banks) derives from *layout* (default: the active
    ``get_layout()``), so moving a pillar moves everything riding on it.
    """
    layout = layout or get_layout()
    L, R = layout.left_col, layout.right_col
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

    # 5. NORTH HIGHWAY (row 7, full width) + return lanes flanking each pillar
    hline(15, 71, NORTH_HWY_ROW, TileType.HIGHWAY)
    hline(15, L - 1, NORTH_HWY_ROW + 1, TileType.HIGHWAY)
    hline(R + 1, 71, NORTH_HWY_ROW + 1, TileType.HIGHWAY)

    # 6. LEFT PILLAR – single highway down the left section
    vline(L, 8, EAST_HWY_ROW, TileType.HIGHWAY)

    # 7. EAST HIGHWAY (row 38)
    hline(L, R, EAST_HWY_ROW, TileType.HIGHWAY)

    # 8. RIGHT PILLAR – single highway up the right section
    vline(R, 8, EAST_HWY_ROW, TileType.HIGHWAY)

    # 10-12. PICK STATIONS — geometry rides the pillars (layout.stations):
    # cart racking block, pick slots hugging the pillar, and parking on the
    # pillar's other side.
    for s in layout.stations:
        fill_rect(s.rack_x0, s.y0, s.rack_x1, s.y1, TileType.RACKING, s.sid)
        for y in range(s.y0, s.y1 + 1):
            put(s.station_col, y, TileType.PICK_STATION, s.sid)

    # 13. PARKING – opposite side of each station
    for s in layout.stations:
        for y in range(s.y0, s.y1 + 1):
            if (s.park_col, y) not in tiles:
                put(s.park_col, y, TileType.PARKING)

    # Gap rows: parking on both sides of each pillar
    left_gap_rows = [9, 15, 16, 21, 22, 27, 28, 33, 34, 35, 36, 37]
    for y in left_gap_rows:
        for x in (L - 1, L + 1):
            if (x, y) not in tiles:
                put(x, y, TileType.PARKING)

    right_gap_rows = [9, 14, 15, 20, 21, 26, 27, 32, 33, 37]
    for y in right_gap_rows:
        for x in (R - 1, R + 1):
            if (x, y) not in tiles:
                put(x, y, TileType.PARKING)

    # Along North Highway (one row above, row 6) — fixed spots; always
    # adjacent to the full-width row-7 highway, so valid for any layout
    for x in [24, 26, 40, 42, 44, 54, 69]:
        if (x, 6) not in tiles:
            put(x, 6, TileType.PARKING)

    # Along East Highway (one row below, row 39), spread along the span
    for x in range(L + 3, R - 1, 6):
        if (x, 39) not in tiles:
            put(x, 39, TileType.PARKING)

    # 14. PRODUCT AISLES — three banks of bi-level pick racking (PRD §14).
    # Not walkable by AGVs; pickers-only territory.
    for (x, y) in aisle_rack_positions():
        put(x, y, TileType.AISLE_RACK)

    return tiles


def build_graph(
    tiles: dict[tuple[int, int], Tile],
    layout: HighwayLayout | None = None,
) -> dict[tuple[int, int], set[tuple[int, int]]]:
    """Build a directed adjacency dict from the tile map.

    Encodes the anti-clockwise one-way loop for highway tiles, plus
    bidirectional access to/from stations and parking. The loop's corner
    junctions and lane ranges follow the pillar columns in *layout*
    (default: the active ``get_layout()``) — it must be the layout the
    tiles were built with.
    """
    layout = layout or get_layout()
    L, R = layout.left_col, layout.right_col
    graph: dict[tuple[int, int], set[tuple[int, int]]] = {}

    highway_positions: set[tuple[int, int]] = set()
    non_highway_positions: set[tuple[int, int]] = set()
    for pos, tile in tiles.items():
        if tile.tile_type == TileType.HIGHWAY:
            highway_positions.add(pos)
        elif tile.tile_type in (
            TileType.PICK_STATION, TileType.PARKING,
            TileType.AGV_SPAWN,
        ):
            non_highway_positions.add(pos)

    all_positions = highway_positions | non_highway_positions

    for pos in all_positions:
        graph[pos] = set()

    # Junction special cases at the pillar corners (pillar cols from layout)
    junctions: dict[tuple[int, int], list[tuple[int, int]]] = {
        # (L,7) must NOT flow west into (L-1,7): row 7 cols 15..L-1 flows east
        # into (L,7), so a westbound edge creates a head-on deadlock 2-cycle
        # at the only connector between the NW corridor and the loop. Spawn-
        # area access is via (L,8) → row 8 → merge north instead.
        (L, 7):  [(0, 1)],
        (L, 8):  [(0, 1), (-1, 0)],
        (L, 38): [(1, 0)],
        (R, 38): [(0, -1)],
        (R, 8):  [(0, -1), (1, 0)],
        (R, 7):  [(-1, 0)],
        (71, 8): [(0, -1)],
    }
    # If a pillar top lands on a Box Depot / Pack-off connector column, keep
    # that column's northward entry alive alongside the junction turn.
    for col in (L, R):
        if 29 <= col <= 36 or 63 <= col <= 66:
            junctions[(col, 7)].append((0, -1))

    def get_highway_directions(x: int, y: int) -> list[tuple[int, int]]:
        """Return list of ``(dx, dy)`` allowed moves for a highway tile."""
        if (x, y) in junctions:
            return junctions[(x, y)]
        if y == 7 and 15 <= x <= L - 1:
            return [(1, 0)]
        if y == 8 and 15 <= x <= L - 1:
            # Westbound return lane may merge north into the eastbound lane
            # (and from there sidetrack into the spawn area). Without the
            # merge, (15,8) is a dead-end trap with no outgoing edges.
            return [(-1, 0), (0, -1)]
        if y == 7 and L + 1 <= x <= 71:
            dirs = [(-1, 0)]
            if 29 <= x <= 36 or 63 <= x <= 66:
                dirs.append((0, -1))  # Box Depot / Pack-off entries
            return dirs
        if x == L and 8 <= y <= 38:
            return [(0, 1)]
        if y == 38 and L <= x <= R:
            return [(1, 0)]
        if x == R and 8 <= y <= 38:
            return [(0, -1)]
        if y == 8 and R + 1 <= x <= 71:
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
                    TileType.AGV_SPAWN,
                ):
                    graph[pos].add(neighbor)
                    graph[neighbor].add(pos)

    return graph


def verify_graph(
    graph: dict[tuple[int, int], set[tuple[int, int]]],
    tiles: dict[tuple[int, int], Tile],
    layout: HighwayLayout | None = None,
) -> None:
    """Log graph stats and test a few key paths at startup."""
    layout = layout or get_layout()
    s1_pick = (layout.left_col - 1, 12)
    s5_pick = (layout.right_col + 1, 35)
    logger.info("--- Graph verification ---")
    logger.info(
        "Highway pillars: L=%d R=%d", layout.left_col, layout.right_col,
    )
    logger.info("Graph nodes: %d", len(graph))
    total_edges = sum(len(v) for v in graph.values())
    logger.info("Graph edges: %d", total_edges)

    tests = [
        (f"Spawn → S1 pick {s1_pick}", AGV_SPAWN_TILE, s1_pick),
        (f"Spawn → S5 pick {s5_pick}", AGV_SPAWN_TILE, s5_pick),
        (f"S1 pick {s1_pick} → Spawn (return)", s1_pick, AGV_SPAWN_TILE),
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
