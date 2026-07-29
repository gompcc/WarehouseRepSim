"""Product aisles: racking geometry, the 2000-SKU catalog, picker walking,
SKU popularity, and toggleable slotting strategies.

Three banks of horizontal bi-level racking runs (see PRD Section 14). Pickers
walk in the walkways between runs and may only enter a walkway at its two
ends — never through racking. Every interior run has pick faces on both sides
(N face serves the walkway above it, S face the walkway below); the top run
of a bank has only a S face and the bottom run only a N face.

Physical **locations** (geometry) are separated from **SKUs** (demand): a
slotting strategy is a permutation assigning SKU ids to locations. SKU id is
popularity rank — SKU 1 is ordered most, with a bell-shaped (half-normal)
demand curve down to SKU 2000 (~90x less frequent).

Slotting strategies (toggle via ``init_catalog(tiles, slotting=...)`` /
``run_headless(slotting=...)``):

- ``sequential``      — SKU k at the k-th location, left→right, top→down.
- ``aisle_proximal``  — same SKUs per aisle as sequential, but within each
                        aisle the popular ones sit nearest the highway /
                        station end; an aisle with a station at either end
                        splits in two with the least popular SKUs in the
                        middle (station↔SKU ownership unchanged).
- ``fibonacci``       — the highway ring is the "center": locations are
                        ranked by distance to the ring and filled in shells
                        whose sizes grow like Fibonacci numbers, most popular
                        shells hugging the track (central aisles naturally
                        invert since their middles are farthest from the
                        ring). Within a shell order stays geometric, spreading
                        hot SKUs around the whole loop.
Zoning (which station's picker owns a location) is purely geometric and does
NOT change with slotting; what changes is which SKU sits where — and hence
each station's demand mix and walking distances.

Walk-time calibration is FROZEN (user decision): the constants below were
fitted once against the *sequential* layout so a pick averages 30 s
(σ 10 s). Slotting experiments must show up as walking-time differences, so
these constants are never re-fitted per strategy.

Scale: 1 tile = METERS_PER_TILE metres; distances returned are in metres.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .enums import TileType
from .constants import (
    NUM_SKUS, METERS_PER_TILE, RACK_LEVELS, PICKER_WALK_SPEED,
    NORTH_HWY_ROW, EAST_HWY_ROW,
)
from .layout import Bank, HighwayLayout, get_layout  # noqa: F401 (Bank re-export)

logger = logging.getLogger(__name__)

SLOTTING_STRATEGIES = ("sequential", "aisle_proximal", "fibonacci")

# Zoning modes (which station's picker owns a location):
# - "nearest":  every location belongs to the closest same-side station —
#   simple, but the middle station of a big bank hoards the zone (under
#   flat demand S7 owned 22% of the catalog and became a mandatory stop
#   on ~99% of orders, strangling throughput).
# - "balanced": same-side stations get EQUAL location budgets, filled
#   nearest-first — every station on a side carries the same demand, so
#   no single station is a near-mandatory stop. (With flat demand, equal
#   locations == equal demand.)
ZONING_MODES = ("nearest", "balanced")

# ----------------------------------------------------------------------
# Pick-cycle calibration (user spec, 2026-07-14, re-specified same day):
# the TOTAL cycle time of a pick — leave cart, walk, grab, walk back —
# has mean 30 s and sd 10 s over the side-constrained geometry (no
# separate grab constant; handling is folded into the fixed term).
# Refit 2026-07-14 evening after side-constrained zoning + S5's 4th slot.
# FROZEN across slotting strategies — placement experiments measure
# walking deltas, so re-fitting per strategy would erase the effect
# being studied.
# ----------------------------------------------------------------------
WALK_TIME_FIXED = 2.9244  # s per pick: fixed handling at cart + slot
WALK_TIME_SCALE = 0.9872  # stretch on the pure distance/speed time


def walk_time_seconds(one_way_m: float) -> float:
    """Calibrated TOTAL pick-cycle time for a slot *one_way_m* metres out
    (round-trip walking + handling; mean 30 s, sd 10 s on the baseline)."""
    return WALK_TIME_FIXED + (2.0 * one_way_m / PICKER_WALK_SPEED) * WALK_TIME_SCALE


# Bank geometry (PRD 14.3) now lives on HighwayLayout — the bank boundary
# facing each pillar moves with it (layout.py). ``Bank`` is re-exported above.


@dataclass(frozen=True)
class Location:
    """One physical pick location (geometry only, no SKU)."""
    index: int        # 1..NUM_SKUS in sequential (geometric) order
    bank: str
    run_row: int
    face: str         # 'N' = picked from the walkway above, 'S' = below
    level: int        # 0 = lower shelf, 1 = upper
    x: float          # slot centre, tile units
    walkway_row: float  # row a picker stands in to pick this location
    walkway_id: tuple[str, int] = ("", 0)  # (bank, walkway index) — one aisle


@dataclass(frozen=True)
class Slot:
    """A SKU bound to a location (the picker/renderer-facing view)."""
    sku: int
    bank: str
    run_row: int
    face: str
    level: int
    x: float
    walkway_row: float
    station: str = ""   # geometric zone owner (picker who serves this slot)


def sku_weight(sku: int) -> float:
    """Demand weight of a SKU — FLAT (user spec 2026-07-15): every product
    is equally likely to appear on an order, so demand is even across the
    2000 locations while each order stays random. (Previously half-normal
    over popularity rank; SKU id remains the rank/sort key the slotting
    strategies order by.)"""
    return 1.0


def _ring_distance(x: float, y: float) -> float:
    """Distance (tiles) from a point to the one-way highway ring."""
    layout = get_layout()
    return min(
        abs(x - layout.left_col), abs(x - layout.right_col),
        abs(y - NORTH_HWY_ROW), abs(y - EAST_HWY_ROW),
    )


def _fibonacci_shells(total: int) -> list[int]:
    """Shell sizes growing like Fibonacci, scaled to sum to *total*."""
    fib = [1, 1]
    while sum(fib) < 34:  # 1 1 2 3 5 8 13 -> 7 shells
        fib.append(fib[-1] + fib[-2])
    scale = total / sum(fib)
    sizes = [max(1, round(f * scale)) for f in fib]
    sizes[-1] += total - sum(sizes)  # exact total
    return sizes


class Catalog:
    """The 2000-SKU catalog: locations, slotting, zoning, walk distances."""

    _build_seq = 0  # unique per-build id (id() reuse would alias caches)

    def __init__(
        self, tiles: dict, slotting: str = "sequential",
        zoning: str = "nearest", batch_release: bool = False,
    ) -> None:
        Catalog._build_seq += 1
        self.catalog_id = Catalog._build_seq
        self.batch_release = batch_release
        if slotting not in SLOTTING_STRATEGIES:
            raise ValueError(
                f"unknown slotting {slotting!r}; pick one of {SLOTTING_STRATEGIES}"
            )
        if zoning not in ZONING_MODES:
            raise ValueError(
                f"unknown zoning {zoning!r}; pick one of {ZONING_MODES}"
            )
        self.slotting = slotting
        self.zoning = zoning
        # Snapshot the active highway layout: banks and side boundaries are
        # frozen into this catalog, so a later set_layout() can't skew a
        # live world — the new geometry only exists after a rebuild.
        self.layout: HighwayLayout = get_layout()
        self.banks: tuple[Bank, ...] = self.layout.banks
        self.station_pos = _station_centroids(tiles)
        self.locations: list[Location] = _layout_locations(self.banks)

        # Geometric zoning: each location belongs to the station with the
        # shortest walk ON ITS OWN SIDE. Pickers cannot cross the one-way
        # highway (user constraint 2026-07-14), so a station only serves
        # the bank on its side: west of the left highway / between the
        # highways / east of the right highway. Bank names match sides.
        def _station_side(sx: float) -> str:
            if sx < self.layout.left_col:
                return "west"
            if sx > self.layout.right_col:
                return "east"
            return "central"

        self.station_side: dict[str, str] = {
            sid: _station_side(sx) for sid, (sx, _sy) in self.station_pos.items()
        }
        self.side_stations: dict[str, list[str]] = {}
        for sid in sorted(self.station_pos):
            self.side_stations.setdefault(self.station_side[sid], []).append(sid)
        self._loc_station: dict[int, str] = {}
        self._loc_walk: dict[int, float] = {}
        if zoning == "balanced":
            # Demand-balanced zoning: same-side stations get EQUAL location
            # budgets, filled nearest-first in geometric order — a station
            # whose nearest-set exceeds its budget spills the overflow to
            # its neighbours, so no station hoards the side (the fix for
            # S7 owning 22% of the catalog under flat demand).
            by_side: dict[str, list[Location]] = {}
            for loc in self.locations:
                by_side.setdefault(loc.bank, []).append(loc)
            for side, locs in by_side.items():
                sids = sorted(
                    s for s in self.station_pos if self.station_side[s] == side
                )
                budget = {s: len(locs) / len(sids) for s in sids}
                for loc in locs:
                    dists = {
                        s: self._walk_distance_to(
                            s, loc.x, loc.walkway_row, loc.bank,
                        )
                        for s in sids
                    }
                    ranked = sorted(sids, key=lambda s: (dists[s], s))
                    target = next(
                        (s for s in ranked if budget[s] >= 1.0), None,
                    )
                    if target is None:
                        target = max(ranked, key=lambda s: budget[s])
                    budget[target] -= 1.0
                    self._loc_station[loc.index] = target
                    self._loc_walk[loc.index] = dists[target]
        else:
            # Nearest zoning: shortest same-side walk wins
            for loc in self.locations:
                best_sid, best_d = None, float("inf")
                for sid in self.station_pos:
                    if self.station_side[sid] != loc.bank:
                        continue
                    d = self._walk_distance_to(
                        sid, loc.x, loc.walkway_row, loc.bank,
                    )
                    if d < best_d:
                        best_sid, best_d = sid, d
                self._loc_station[loc.index] = best_sid
                self._loc_walk[loc.index] = best_d

        # Slotting: permutation sku -> location
        assign = {
            "sequential": _assign_sequential,
            "aisle_proximal": _assign_aisle_proximal,
            "fibonacci": _assign_fibonacci,
        }[slotting]
        sku_to_loc: dict[int, Location] = assign(
            self.locations, self._loc_station, self._loc_walk,
        )

        self.slots: dict[int, Slot] = {}
        self.station_skus: dict[str, list[int]] = {s: [] for s in self.station_pos}
        self.weights: dict[int, float] = {}
        # sku -> geometric location index (1..NUM_SKUS along the aisles);
        # the GUI's location spectrum plots pick frequency over this axis
        self.sku_location_index: dict[int, int] = {
            sku: loc.index for sku, loc in sku_to_loc.items()
        }
        for sku, loc in sku_to_loc.items():
            station = self._loc_station[loc.index]
            self.slots[sku] = Slot(
                sku=sku, bank=loc.bank, run_row=loc.run_row, face=loc.face,
                level=loc.level, x=loc.x, walkway_row=loc.walkway_row,
                station=station,
            )
            self.station_skus[station].append(sku)
            self.weights[sku] = sku_weight(sku)
        for skus in self.station_skus.values():
            skus.sort()

        counts = {s: len(v) for s, v in sorted(self.station_skus.items())}
        logger.info(
            "[Aisles] Catalog (slotting=%s): %d SKUs zoned %s | demand-weighted"
            " walk %.1f m one-way",
            slotting, len(self.slots), counts, self.demand_weighted_walk_m(),
        )

    # -- walking -----------------------------------------------------------

    def _walk_distance_to(
        self, station_id: str, x: float, walkway_row: float, bank_name: str,
    ) -> float:
        bank = next(b for b in self.banks if b.name == bank_name)
        sx, sy = self.station_pos[station_id]
        best = float("inf")
        for end_x in (bank.col_start - 0.5, bank.col_end + 0.5):
            d = abs(sx - end_x) + abs(sy - walkway_row) + abs(x - end_x)
            best = min(best, d)
        return best * METERS_PER_TILE

    def walk_path(
        self, station_id: str, sku: int,
    ) -> list[tuple[float, float]]:
        """Waypoints (tile units) from the station to the slot, entering the
        walkway at its nearer end. Used for distance and picker animation."""
        slot = self.slots[sku]
        bank = next(b for b in self.banks if b.name == slot.bank)
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
        slot = self.slots[sku]
        return self._walk_distance_to(
            station_id, slot.x, slot.walkway_row, slot.bank,
        )

    def station_of(self, sku: int) -> str:
        return self.slots[sku].station

    def side_skus(self, side: str) -> list[int]:
        """All SKUs slotted on *side* (any zone) — the pool a station's
        pickers draw from under batched release. Cached."""
        if not hasattr(self, "_side_skus"):
            out: dict[str, list[int]] = {}
            for sku, slot in self.slots.items():
                out.setdefault(slot.bank, []).append(sku)
            for skus in out.values():
                skus.sort()
            self._side_skus = out
        return self._side_skus.get(side, [])

    def batched_release_map(self, skus: list[int], order_id: int) -> dict[int, str]:
        """Zone-batched order release (2-pager recommendation #4): every
        line on a side is assigned to ONE same-side station, so an order
        visits at most one station per side (~3 stops instead of ~8 under
        flat 20-line orders — the stations-per-order tax is set upstream
        by the WMS, free to fix in software). The station rotates with the
        order id: under flat demand the walk-optimal choice would send
        every order to the same centroid station and saturate its 4-5
        cart slots, so spreading orders across each side's stations keeps
        every station's slots in play. Pickers legally reach any same-side
        slot (they never cross the highway); the longer cross-zone walks
        are priced by walk_distance/walk_time_seconds as usual."""
        result: dict[int, str] = {}
        for sku in skus:
            side = self.slots[sku].bank
            sids = self.side_stations[side]
            result[sku] = sids[order_id % len(sids)]
        return result

    # -- demand ------------------------------------------------------------

    def _weighted_sample(self, pool: list[int], n: int, rng) -> list[int]:
        """Popularity-weighted sample WITHOUT replacement from *pool*."""
        if not pool:
            return []
        n = min(n, len(pool))
        pool = list(pool)
        weights = [self.weights[s] for s in pool]
        chosen: list[int] = []
        for _ in range(n):
            r = rng.random() * sum(weights)
            acc = 0.0
            for i, w in enumerate(weights):
                acc += w
                if acc >= r:
                    chosen.append(pool.pop(i))
                    weights.pop(i)
                    break
        return sorted(chosen)

    def sample_skus(self, n: int, rng) -> list[int]:
        """Popularity-weighted sample WITHOUT replacement from the whole
        catalog (SKU space) — demand independent of slot placement, so
        every slotting strategy faces the identical order stream."""
        return self._weighted_sample(sorted(self.slots), n, rng)

    def zone_border_segments(self) -> list[tuple[str, int, str, float, float, str]]:
        """Contiguous same-owner spans along each racking face, for the map.

        Returns ``(bank, run_row, face, x_start, x_end, station_id)`` per
        span. Purely geometric (nearest-walk zoning of *locations*), so the
        segments are identical under every slotting strategy. The two faces
        of a run are independent, and a face split between stations yields
        one segment per owner (segmented borders).
        """
        if not hasattr(self, "_zone_segments"):
            faces: dict[tuple[str, int, str], dict[float, str]] = {}
            for loc in self.locations:
                key = (loc.bank, loc.run_row, loc.face)
                faces.setdefault(key, {})[loc.x] = self._loc_station[loc.index]
            segments: list[tuple[str, int, str, float, float, str]] = []
            for (bank, run_row, face), by_x in faces.items():
                b = next(bk for bk in self.banks if bk.name == bank)
                xs = sorted(by_x)
                pitch = xs[1] - xs[0] if len(xs) > 1 else 1.0
                seg_start = max(xs[0] - pitch / 2, float(b.col_start))
                owner = by_x[xs[0]]
                for prev, x in zip(xs, xs[1:]):
                    if by_x[x] != owner:
                        mid = (prev + x) / 2
                        segments.append((bank, run_row, face, seg_start, mid, owner))
                        seg_start, owner = mid, by_x[x]
                seg_end = min(xs[-1] + pitch / 2, float(b.col_end + 1))
                segments.append((bank, run_row, face, seg_start, seg_end, owner))
            self._zone_segments = segments
        return self._zone_segments

    def demand_weighted_walk_m(self) -> float:
        """Mean one-way walk per pick, weighted by SKU demand — THE slotting
        comparison metric (calibration constants stay frozen)."""
        total_w = 0.0
        total_d = 0.0
        for sku, slot in self.slots.items():
            w = self.weights[sku]
            total_w += w
            total_d += w * self.walk_distance(slot.station, sku)
        return total_d / total_w if total_w else 0.0

    def longest_walk_m(self) -> dict[str, float]:
        """Worst-case one-way pick walk (metres) per station: the farthest
        slot in each station's zone. Deterministic per layout+zoning (does
        not depend on slotting — the zone's farthest LOCATION sets it, and
        zoning is geometric). Shown on the map next to each station."""
        if not hasattr(self, "_longest_walk"):
            self._longest_walk = {
                sid: max(
                    (self.walk_distance(sid, sku) for sku in skus),
                    default=0.0,
                )
                for sid, skus in self._pick_pool().items()
            }
        return self._longest_walk

    def _pick_pool(self) -> dict[str, list[int]]:
        """The SKUs a station's pickers actually fetch: its zone normally,
        its whole SIDE under batched release (an order's side batch lands
        on any same-side station, so walk stats and the auto-staffing
        service rate must price side-wide walks or management would
        systematically understaff)."""
        if self.batch_release:
            return {
                sid: self.side_skus(self.station_side[sid])
                for sid in self.station_pos
            }
        return self.station_skus

    def station_avg_walk_s(self) -> dict[str, float]:
        """Popularity-weighted mean pick-cycle time (s) per station: the
        expected calibrated walk+handle time of one pick there, weighting
        each zoned SKU by its order popularity — the per-station analogue
        of ``demand_weighted_walk_m``. Shown on the map (``μNNs``). Cached."""
        if not hasattr(self, "_station_avg_walk"):
            out: dict[str, float] = {}
            for sid, skus in self._pick_pool().items():
                total_w = 0.0
                total_t = 0.0
                for sku in skus:
                    w = self.weights[sku]
                    total_w += w
                    total_t += w * walk_time_seconds(self.walk_distance(sid, sku))
                out[sid] = total_t / total_w if total_w else 0.0
            self._station_avg_walk = out
        return self._station_avg_walk

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


# ----------------------------------------------------------------------
# Geometry
# ----------------------------------------------------------------------

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


def _layout_locations(banks: tuple[Bank, ...]) -> list[Location]:
    """Lay out exactly NUM_SKUS locations across all active faces and levels.

    All (face, level) strips are concatenated into one line; location centres
    are placed uniformly along it, then mapped back to their strip. This
    yields exactly NUM_SKUS locations with a uniform derived slot width —
    so when a pillar move lengthens one side's aisles, that side gains
    locations (and the other side loses them) at unchanged density.
    """
    strips: list[tuple[Bank, int, str, int, float, int]] = []
    for bank in banks:
        run_len = (bank.col_end - bank.col_start + 1) * METERS_PER_TILE
        rows = bank.run_rows
        for i, row in enumerate(rows):
            # face -> walkway index within the bank (aisle identity)
            faces: list[tuple[str, int]] = []
            if i > 0:
                faces.append(("N", i - 1))  # walkway above this run
            if i < len(rows) - 1:
                faces.append(("S", i))      # walkway below this run
            for face, walkway in faces:
                for level in range(RACK_LEVELS):
                    strips.append((bank, row, face, level, run_len, walkway))

    total_len = sum(s[4] for s in strips)
    slot_width = total_len / NUM_SKUS

    locations: list[Location] = []
    strip_idx = 0
    strip_start = 0.0
    for index in range(1, NUM_SKUS + 1):
        centre = (index - 0.5) * slot_width
        while centre > strip_start + strips[strip_idx][4]:
            strip_start += strips[strip_idx][4]
            strip_idx += 1
        bank, row, face, level, _len, walkway = strips[strip_idx]
        offset_m = centre - strip_start
        x = bank.col_start + offset_m / METERS_PER_TILE - 0.5
        walkway_row = row - 1.0 if face == "N" else row + 1.0
        locations.append(Location(
            index=index, bank=bank.name, run_row=row, face=face,
            level=level, x=x, walkway_row=walkway_row,
            walkway_id=(bank.name, walkway),
        ))
    return locations


# ----------------------------------------------------------------------
# Slotting strategies — each returns {sku: Location}
# ----------------------------------------------------------------------

def _assign_sequential(locations, loc_station, loc_walk) -> dict[int, Location]:
    """SKU k at the k-th location (popularity ignores geography)."""
    return {loc.index: loc for loc in locations}


def _assign_aisle_proximal(locations, loc_station, loc_walk) -> dict[int, Location]:
    """Sequential's SKUs per (aisle, station) subgroup, re-ordered inside the
    subgroup so the most popular SKU sits nearest the subgroup's station end
    of the aisle — i.e. nearest the highway, since stations hug the ring.
    An aisle with a station at either end is split at the zone boundary and
    each half fills popular-first from its own end, so the least popular
    SKUs meet in the middle (user spec 2026-07-14). Station↔SKU ownership
    is identical to sequential."""
    groups: dict[tuple, list[Location]] = {}
    for loc in locations:
        groups.setdefault((loc.walkway_id, loc_station[loc.index]), []).append(loc)
    out: dict[int, Location] = {}
    for group in groups.values():
        skus = sorted(loc.index for loc in group)         # popularity order
        by_dist = sorted(group, key=lambda l: (loc_walk[l.index], l.index))
        for sku, loc in zip(skus, by_dist):
            out[sku] = loc
    return out


def _assign_fibonacci(locations, loc_station, loc_walk) -> dict[int, Location]:
    """Fibonacci shells around the highway ring: the hottest SKUs live in the
    thin innermost shell hugging the track, shell sizes growing golden-ratio
    style outwards. Within a shell the geometric order is kept, so hot SKUs
    spread around the whole loop instead of clumping."""
    ranked = sorted(
        locations, key=lambda l: (_ring_distance(l.x, l.walkway_row), l.index),
    )
    out: dict[int, Location] = {}
    sku = 1
    for size in _fibonacci_shells(len(ranked)):
        shell = sorted(ranked[:size], key=lambda l: l.index)  # geometric order
        ranked = ranked[size:]
        for loc in shell:
            out[sku] = loc
            sku += 1
    return out



# ----------------------------------------------------------------------
# Module-level singleton (built once per Environment)
# ----------------------------------------------------------------------

_catalog: Catalog | None = None


def init_catalog(
    tiles: dict, slotting: str = "sequential", zoning: str = "nearest",
    batch_release: bool = False,
) -> Catalog:
    """Build (or rebuild) the catalog from the live tile map."""
    global _catalog
    _catalog = Catalog(
        tiles, slotting=slotting, zoning=zoning, batch_release=batch_release,
    )
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
    """All (x, y) tiles occupied by racking runs (for map building/drawing),
    per the ACTIVE highway layout."""
    positions: list[tuple[int, int]] = []
    for bank in get_layout().banks:
        for row in bank.run_rows:
            for x in range(bank.col_start, bank.col_end + 1):
                positions.append((x, row))
    return positions
