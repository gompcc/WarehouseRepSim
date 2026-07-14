"""Product aisles: racking geometry, the 2000-SKU catalog, and picker walking.

Three banks of horizontal bi-level racking runs (see PRD Section 14). Pickers
walk in the walkways between runs and may only enter a walkway at its two
ends — never through racking. Every interior run has pick faces on both sides
(N face serves the walkway above it, S face the walkway below); the top run
of a bank has only a S face and the bottom run only a N face.

The catalog assigns every SKU (1..NUM_SKUS) one slot and zones each slot to
the S station with the shortest walking distance. Layout is fully
deterministic — no RNG — so SKU positions are stable across runs.

Scale: 1 tile = METERS_PER_TILE metres; distances returned are in metres.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from .enums import TileType
from .constants import (
    NUM_SKUS, METERS_PER_TILE, RACK_LEVELS, PICKER_WALK_SPEED,
)

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Walk-time calibration (user spec, 2026-07-14): the round-trip walking
# time per pick, over all (station, zoned SKU) pairs, must have mean 30 s
# and sd 10 s — "near" picks ~20 s, "far" ~40 s. The raw geometry gives
# mean 26.2 s / sd 9.7 s at 1.4 m/s; the affine fit below maps it to the
# target exactly (measured p16 = 19.7 s, p84 = 41.3 s — matching the
# near-20 / far-40 intent). Re-derive with calibration_stats() if the
# bank geometry ever changes.
# ----------------------------------------------------------------------
WALK_TIME_FIXED = 2.93   # s per pick: leaving/re-approaching the cart
WALK_TIME_SCALE = 1.0330  # stretch on the pure distance/speed time


def walk_time_seconds(one_way_m: float) -> float:
    """Calibrated round-trip walking time for a pick at *one_way_m* metres."""
    return WALK_TIME_FIXED + (2.0 * one_way_m / PICKER_WALK_SPEED) * WALK_TIME_SCALE


@dataclass(frozen=True)
class Bank:
    name: str
    col_start: int   # first racking column (inclusive)
    col_end: int     # last racking column (inclusive)
    run_rows: tuple[int, ...]  # rows containing a racking run, top to bottom


# Geometry per PRD 14.3 (coordinates are post-expansion grid columns/rows)
BANKS: tuple[Bank, ...] = (
    Bank("west", 0, 12, (10, 13, 16, 19, 22, 25, 28, 31, 34, 37)),
    Bank("central", 31, 45, (12, 15, 18, 21, 24, 27, 30, 33)),
    Bank("east", 60, 84, (10, 13, 16, 19, 22, 25, 28, 31, 34, 37)),
)


@dataclass(frozen=True)
class Slot:
    """One pick location. ``x`` is in tile units; walking uses metres."""
    sku: int
    bank: str
    run_row: int
    face: str         # 'N' = picked from the walkway above, 'S' = below
    level: int        # 0 = lower shelf, 1 = upper
    x: float          # slot centre, tile units
    walkway_row: float  # row a picker stands in to pick this slot
    station: str = ""   # assigned S station (set during catalog build)


class Catalog:
    """The 2000-SKU catalog: slots, station zoning, and walk distances."""

    def __init__(self, tiles: dict) -> None:
        self.station_pos = _station_centroids(tiles)
        self.slots: dict[int, Slot] = _layout_slots()
        self.station_skus: dict[str, list[int]] = {s: [] for s in self.station_pos}
        for sku, slot in self.slots.items():
            station = min(
                self.station_pos,
                key=lambda s: self.walk_distance(s, sku),
            )
            self.slots[sku] = replace(slot, station=station)
            self.station_skus[station].append(sku)
        counts = {s: len(v) for s, v in sorted(self.station_skus.items())}
        logger.info("[Aisles] Catalog: %d SKUs zoned %s", len(self.slots), counts)

    def station_of(self, sku: int) -> str:
        return self.slots[sku].station

    def walk_path(
        self, station_id: str, sku: int,
    ) -> list[tuple[float, float]]:
        """Waypoints (tile units) from the station to the slot, entering the
        walkway at its nearer end. Used for distance and picker animation."""
        slot = self.slots[sku]
        bank = next(b for b in BANKS if b.name == slot.bank)
        sx, sy = self.station_pos[station_id]
        wy = slot.walkway_row
        best: list[tuple[float, float]] | None = None
        best_d = float("inf")
        for end_x in (bank.col_start - 0.5, bank.col_end + 0.5):
            # Manhattan to the walkway entrance, then straight down the aisle
            d = abs(sx - end_x) + abs(sy - wy) + abs(slot.x - end_x)
            if d < best_d:
                best_d = d
                best = [(sx, sy), (end_x, sy), (end_x, wy), (slot.x, wy)]
        assert best is not None
        return best

    def walk_distance(self, station_id: str, sku: int) -> float:
        """One-way walking distance in metres from station to slot."""
        path = self.walk_path(station_id, sku)
        d = 0.0
        for (x1, y1), (x2, y2) in zip(path, path[1:]):
            d += abs(x2 - x1) + abs(y2 - y1)
        return d * METERS_PER_TILE

    def calibration_stats(self) -> dict:
        """Distribution of calibrated round-trip walk times per pick over
        every (station, zoned SKU) pair. Cached; used by the GUI and tests."""
        if not hasattr(self, "_calib"):
            times = sorted(
                walk_time_seconds(self.walk_distance(sid, sku))
                for sid, skus in self.station_skus.items()
                for sku in skus
            )
            n = len(times)
            mean = sum(times) / n
            var = sum((t - mean) ** 2 for t in times) / (n - 1)
            self._calib = {
                "mean_s": mean,
                "sd_s": var ** 0.5,
                "near_p16_s": times[16 * n // 100],
                "mid_p50_s": times[n // 2],
                "far_p84_s": times[84 * n // 100],
                "min_s": times[0],
                "max_s": times[-1],
            }
        return self._calib


def _station_centroids(tiles: dict) -> dict[str, tuple[float, float]]:
    """Mean position of each S station's PICK_STATION tiles (cart spots)."""
    acc: dict[str, list[tuple[int, int]]] = {}
    for (x, y), tile in tiles.items():
        if tile.tile_type == TileType.PICK_STATION and tile.station_id:
            acc.setdefault(tile.station_id, []).append((x, y))
    return {
        sid: (sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps))
        for sid, ps in acc.items()
    }


def _layout_slots() -> dict[int, Slot]:
    """Lay out exactly NUM_SKUS slots across all active faces and levels.

    All (face, level) strips are concatenated into one line; slot centres are
    placed uniformly along it, then mapped back to their strip. This yields
    exactly NUM_SKUS slots with a uniform derived slot width.
    """
    strips: list[tuple[Bank, int, str, int, float]] = []  # +face length (m)
    for bank in BANKS:
        run_len = (bank.col_end - bank.col_start + 1) * METERS_PER_TILE
        rows = bank.run_rows
        for i, row in enumerate(rows):
            faces = []
            if i > 0:
                faces.append("N")  # walkway between rows[i-1] and this run
            if i < len(rows) - 1:
                faces.append("S")  # walkway below
            for face in faces:
                for level in range(RACK_LEVELS):
                    strips.append((bank, row, face, level, run_len))

    total_len = sum(s[4] for s in strips)
    slot_width = total_len / NUM_SKUS
    logger.info(
        "[Aisles] %d strips, %.0f m of pick face x %d levels -> slot width %.3f m",
        len(strips), total_len / RACK_LEVELS * 1.0, RACK_LEVELS, slot_width,
    )

    slots: dict[int, Slot] = {}
    strip_idx = 0
    strip_start = 0.0  # cumulative start of current strip along the line
    for sku in range(1, NUM_SKUS + 1):
        centre = (sku - 0.5) * slot_width
        while centre > strip_start + strips[strip_idx][4]:
            strip_start += strips[strip_idx][4]
            strip_idx += 1
        bank, row, face, level, _len = strips[strip_idx]
        offset_m = centre - strip_start
        x = bank.col_start + offset_m / METERS_PER_TILE - 0.5
        walkway_row = row - 1.0 if face == "N" else row + 1.0
        slots[sku] = Slot(
            sku=sku, bank=bank.name, run_row=row, face=face,
            level=level, x=x, walkway_row=walkway_row,
        )
    return slots


# ----------------------------------------------------------------------
# Module-level singleton (built once per Environment)
# ----------------------------------------------------------------------

_catalog: Catalog | None = None


def init_catalog(tiles: dict) -> Catalog:
    """Build (or rebuild) the catalog from the live tile map."""
    global _catalog
    _catalog = Catalog(tiles)
    return _catalog


def get_catalog() -> Catalog:
    """Return the catalog, lazily building it from the standard map.

    Environment() initialises it explicitly; the lazy path exists so that
    Order() and unit tests work without constructing an Environment. The
    geometry is deterministic, so both paths yield the identical catalog."""
    global _catalog
    if _catalog is None:
        from .map_builder import build_map  # runtime import: avoids cycle
        _catalog = Catalog(build_map())
    return _catalog


def aisle_rack_positions() -> list[tuple[int, int]]:
    """All (x, y) tiles occupied by racking runs (for map building/drawing)."""
    positions: list[tuple[int, int]] = []
    for bank in BANKS:
        for row in bank.run_rows:
            for x in range(bank.col_start, bank.col_end + 1):
                positions.append((x, row))
    return positions
