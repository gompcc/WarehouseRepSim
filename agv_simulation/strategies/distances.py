"""Directed travel-distance maps for the warehouse graph.

The highways form an anti-clockwise one-way loop, with bidirectional
parking "ladders" alongside each station bank. Manhattan distance is a fair
proxy *within* a bank (the ladder allows short backward moves) but
underprices cross-bank trips ~2x: the left and right banks only connect via
the top/bottom highways. These maps give true directed hop distances from
*every* graph node to each station, precomputed once via multi-source BFS
on the reversed graph (one BFS per station, ~600 nodes each).
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from ..enums import TileType
from ..constants import TILE_TRAVEL_TIME

if TYPE_CHECKING:
    from ..models import Tile

INF = float("inf")


class DistanceMap:
    """Directed hop distance from any node to each station's dwell tiles."""

    def __init__(
        self,
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        station_tiles: dict[tuple[str | None, TileType], list[tuple[int, int]]],
    ) -> None:
        reversed_graph: dict[tuple[int, int], list[tuple[int, int]]] = {
            pos: [] for pos in graph
        }
        for pos, neighbors in graph.items():
            for nb in neighbors:
                reversed_graph[nb].append(pos)

        # Same station→tile-type convention as the Dispatcher
        self._dist: dict[str, dict[tuple[int, int], int]] = {}
        for (sid, tile_type), positions in station_tiles.items():
            if sid is None:
                continue
            expected = (
                TileType.PICK_STATION if sid.startswith("S") else TileType.PARKING
            )
            if tile_type != expected:
                continue
            self._dist[sid] = self._reverse_bfs(reversed_graph, positions)

    @staticmethod
    def _reverse_bfs(
        reversed_graph: dict[tuple[int, int], list[tuple[int, int]]],
        sources: list[tuple[int, int]],
    ) -> dict[tuple[int, int], int]:
        dist: dict[tuple[int, int], int] = {}
        queue: deque[tuple[int, int]] = deque()
        for src in sources:
            if src in reversed_graph:
                dist[src] = 0
                queue.append(src)
        while queue:
            node = queue.popleft()
            for pred in reversed_graph[node]:
                if pred not in dist:
                    dist[pred] = dist[node] + 1
                    queue.append(pred)
        return dist

    def hops_to_station(self, pos: tuple[int, int], station_id: str) -> float:
        """Directed hop count from *pos* to the nearest tile of *station_id*."""
        return self._dist.get(station_id, {}).get(pos, INF)

    def seconds_to_station(self, pos: tuple[int, int], station_id: str) -> float:
        """Directed travel time (seconds) from *pos* to *station_id*."""
        hops = self.hops_to_station(pos, station_id)
        return hops * TILE_TRAVEL_TIME if hops != INF else INF
