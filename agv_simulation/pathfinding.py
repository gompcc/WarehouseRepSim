"""A* pathfinding on the warehouse graph."""

from __future__ import annotations

import heapq

from .enums import TileType
from .constants import LEFT_HWY_COL, RIGHT_HWY_COL

# Tiles immediately adjacent to highways can serve as overflow lanes
_SIDETRACK_COLS = frozenset({
    LEFT_HWY_COL - 1, LEFT_HWY_COL + 1,   # cols 8, 10
    RIGHT_HWY_COL - 1, RIGHT_HWY_COL + 1,  # cols 37, 39
})


def astar(
    graph: dict[tuple[int, int], set[tuple[int, int]]],
    start: tuple[int, int],
    goal: tuple[int, int],
    blocked: set[tuple[int, int]] | None = None,
    tiles: dict | None = None,
) -> list[tuple[int, int]] | None:
    """A* with Manhattan distance heuristic and weighted edge costs.

    Highway tiles cost 1, sidetrack tiles (adjacent to highway) cost 2,
    all other walkable tiles cost 10.
    Returns list of ``(x, y)`` from *start* to *goal* inclusive, or ``None`` if no path.
    """
    if start not in graph or goal not in graph:
        return None

    def h(node: tuple[int, int]) -> int:
        return abs(node[0] - goal[0]) + abs(node[1] - goal[1])

    counter = 0
    open_set: list[tuple[int, int, tuple[int, int]]] = [(h(start), counter, start)]
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], float] = {start: 0}

    while open_set:
        f, _, current = heapq.heappop(open_set)

        if current == goal:
            path: list[tuple[int, int]] = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path

        for neighbor in graph.get(current, set()):
            if blocked and neighbor in blocked and neighbor != goal:
                continue
            if tiles and neighbor != goal:
                tile = tiles.get(neighbor)
                if tile and tile.tile_type == TileType.HIGHWAY:
                    edge_cost = 1
                elif neighbor[0] in _SIDETRACK_COLS and tile and tile.tile_type == TileType.PARKING:
                    edge_cost = 2  # overflow lane adjacent to highway
                else:
                    edge_cost = 10
            else:
                edge_cost = 1
            tentative_g = g_score[current] + edge_cost
            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                counter += 1
                heapq.heappush(open_set, (tentative_g + h(neighbor), counter, neighbor))

    return None
