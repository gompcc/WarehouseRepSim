"""Dynamic highway layout: the two vertical highway pillars are parameters.

Everything physically attached to a pillar derives from its column here, in
one place: the pick stations (S1-S4 ride the left pillar, S5-S9 the right),
their cart racking and parking, and the aisle bank boundaries. Moving a
pillar therefore changes the aisle lengths on each side of it — and since
the catalog spreads NUM_SKUS uniformly over total aisle length, also how
many products live on each side and how far pickers walk for them.

The active layout is a module singleton (same pattern as ``aisles._catalog``):
``build_map()``, ``build_graph()``, ``Catalog`` and ``astar`` all read
``get_layout()``, so changing the layout is ``set_layout(...)`` followed by a
world rebuild. The default layout reproduces the classic fixed map exactly.

Fixed by design (only the pillar COLUMNS move): the highway ring rows, the
station row spans, the run rows within each bank, the AGV spawn area, Box
Depot and Pack-off.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import LEFT_HWY_COL, RIGHT_HWY_COL

# Movement bounds.
# left >= 16: keeps at least one eastbound spawn-corridor tile (cols 15..L-1)
#             and a non-degenerate west bank (cols 0..L-11).
# right <= 70: keeps the row-8 return lane (cols R+1..71) and a non-degenerate
#             east bank (cols R+8..84).
# gap >= 17: central bank (cols L+8..R-7) keeps >= 3 columns between the two
#             pillars' station racking blocks.
LEFT_COL_MIN = 16
RIGHT_COL_MAX = 70
MIN_PILLAR_GAP = 17

# Throughput-optimal pillar columns from experiments/run_highway_sweep.py
# (re-swept 2026-07-29 under the winning policy stack — flat demand +
# picker mgmt + extra slots + batched release: 70-layout screen + 2h x
# 3-seed confirm, 61.8 orders/hr mean vs 55.8 at the classic (23, 52),
# 10 AGV / 25 cart fleet). Wide span wins under batching: it grows the
# 4-station central bank. The old (16, 50) optimum was bare-baseline
# under popularity demand — layout optima are CONDITIONAL on policy.
# The GUI's panel button jumps straight here.
OPTIMAL_HIGHWAY: tuple[int, int] = (25, 68)

# Racking run rows per bank (fixed; only column spans move with the pillars)
WEST_RUN_ROWS = (10, 13, 16, 19, 22, 25, 28, 31, 34, 37)
CENTRAL_RUN_ROWS = (12, 15, 18, 21, 24, 27, 30, 33)
EAST_RUN_ROWS = (10, 13, 16, 19, 22, 25, 28, 31, 34, 37)
EAST_BANK_END = 84


@dataclass(frozen=True)
class Bank:
    name: str
    col_start: int   # first racking column (inclusive)
    col_end: int     # last racking column (inclusive)
    run_rows: tuple[int, ...]  # rows containing a racking run, top to bottom


@dataclass(frozen=True)
class StationSpec:
    """One S station's geometry, all columns relative to its pillar."""
    sid: str
    station_col: int  # PICK_STATION (cart slot) column, hugging the pillar
    park_col: int     # parking column on the pillar's other side
    rack_x0: int      # station cart-racking block, first column
    rack_x1: int      # ... last column (inclusive)
    y0: int           # first row (inclusive)
    y1: int           # last row (inclusive)
    extra_row: int = 0  # row of the optional extra slot (extra_slots layout)


@dataclass(frozen=True)
class HighwayLayout:
    left_col: int = LEFT_HWY_COL
    right_col: int = RIGHT_HWY_COL
    # Extra-slot strategy: every station gains one PICK_STATION tile in
    # the free gap row just below its column (S5 above — row 38 below it
    # is the East Highway), replacing that row's overflow parking.
    extra_slots: bool = False

    def __post_init__(self) -> None:
        if not (
            LEFT_COL_MIN <= self.left_col
            and self.right_col <= RIGHT_COL_MAX
            and self.right_col - self.left_col >= MIN_PILLAR_GAP
        ):
            raise ValueError(
                f"invalid highway layout L={self.left_col} R={self.right_col}: "
                f"need {LEFT_COL_MIN} <= L, R <= {RIGHT_COL_MAX}, "
                f"R - L >= {MIN_PILLAR_GAP}"
            )

    def move_pillar(self, pillar: str, col: int) -> "HighwayLayout":
        """Return a layout with one pillar moved to *col*, clamped to bounds."""
        if pillar == "left":
            col = max(LEFT_COL_MIN, min(col, self.right_col - MIN_PILLAR_GAP))
            return HighwayLayout(col, self.right_col, self.extra_slots)
        if pillar == "right":
            col = max(self.left_col + MIN_PILLAR_GAP, min(col, RIGHT_COL_MAX))
            return HighwayLayout(self.left_col, col, self.extra_slots)
        raise ValueError(f"unknown pillar {pillar!r}")

    @property
    def banks(self) -> tuple[Bank, ...]:
        """Aisle banks; the boundaries facing a pillar move with it."""
        return (
            Bank("west", 0, self.left_col - 11, WEST_RUN_ROWS),
            Bank("central", self.left_col + 8, self.right_col - 7,
                 CENTRAL_RUN_ROWS),
            Bank("east", self.right_col + 8, EAST_BANK_END, EAST_RUN_ROWS),
        )

    @property
    def stations(self) -> tuple[StationSpec, ...]:
        """S1-S9 geometry. Rows are fixed; columns ride the pillars."""
        L, R = self.left_col, self.right_col
        return (
            # Left pillar: S1/S3 face west, S2/S4 face central. extra_row
            # is the free gap row below the slot column (S5: above).
            StationSpec("S1", L - 1, L + 1, L - 5, L - 2, 10, 14, 15),
            StationSpec("S2", L + 1, L - 1, L + 2, L + 7, 17, 20, 21),
            StationSpec("S3", L - 1, L + 1, L - 5, L - 2, 23, 26, 27),
            StationSpec("S4", L + 1, L - 1, L + 2, L + 7, 29, 32, 33),
            # Right pillar: S5/S7/S9 face east, S6/S8 face central
            StationSpec("S5", R + 1, R - 1, R + 2, R + 6, 34, 37, 33),
            StationSpec("S6", R - 1, R + 1, R - 6, R - 2, 28, 31, 32),
            StationSpec("S7", R + 1, R - 1, R + 2, R + 6, 22, 25, 26),
            StationSpec("S8", R - 1, R + 1, R - 6, R - 2, 16, 19, 20),
            StationSpec("S9", R + 1, R - 1, R + 2, R + 6, 10, 13, 14),
        )

    @property
    def sidetrack_cols(self) -> frozenset[int]:
        """Columns whose parking tiles serve as highway overflow lanes."""
        return frozenset({
            self.left_col - 1, self.left_col + 1,
            self.right_col - 1, self.right_col + 1,
        })


_layout: HighwayLayout = HighwayLayout()


def get_layout() -> HighwayLayout:
    return _layout


def set_layout(layout: HighwayLayout) -> HighwayLayout:
    """Install *layout* as the active geometry. The world (map, graph,
    catalog, dispatcher) must be rebuilt afterwards — live entities hold
    positions and paths from the old geometry."""
    global _layout
    _layout = layout
    return _layout
