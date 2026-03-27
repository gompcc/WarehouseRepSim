"""A* pathfinding on the warehouse graph."""

from __future__ import annotations

import heapq
import logging

from .enums import TileType

logger = logging.getLogger(__name__)


def _edge_cost(tiles: dict | None, neighbor: tuple[int, int], goal: tuple[int, int]) -> int:
    """Return movement cost for stepping onto *neighbor*.

    Highway tiles cost 1; all other walkable tiles cost 10.
    The *goal* tile always costs 1 so the destination is never penalised.
    When *tiles* is ``None`` every step costs 10 (conservative — no highway data).
    """
    if neighbor == goal:
        return 1
    if tiles:
        tile = tiles.get(neighbor)
        return 1 if (tile and tile.tile_type == TileType.HIGHWAY) else 10
    return 10


def astar(
    graph: dict[tuple[int, int], set[tuple[int, int]]],
    start: tuple[int, int],
    goal: tuple[int, int],
    blocked: set[tuple[int, int]] | None = None,
    tiles: dict | None = None,
) -> list[tuple[int, int]] | None:
    """A* with Manhattan distance heuristic and weighted edge costs.

    Highway tiles cost 1, all other walkable tiles cost 10.
    Returns list of ``(x, y)`` from *start* to *goal* inclusive, or ``None`` if no path.
    """
    if start not in graph or goal not in graph:
        logger.warning("astar: node not in graph (start=%s in=%s, goal=%s in=%s)",
                        start, start in graph, goal, goal in graph)
        return None

    if tiles is None:
        logger.warning("astar: tiles=None, all edges default to cost 1 (no highway preference)")

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
            tentative_g = g_score[current] + _edge_cost(tiles, neighbor, goal)
            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                counter += 1
                heapq.heappush(open_set, (tentative_g + h(neighbor), counter, neighbor))

    return None
