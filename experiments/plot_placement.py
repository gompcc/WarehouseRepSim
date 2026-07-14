"""Placement visualization: SKU-popularity maps per slotting strategy + the
walk-time comparison bar chart.

Usage:
    ./venv/bin/python experiments/plot_placement.py

Writes results/figures/slotting_popularity_maps.png and
results/figures/walk_time_by_slotting.png (PNGs are gitignored artifacts;
re-run this script to regenerate).

Chart styling follows the dataviz method: sequential magnitude = one blue
ramp light->dark; nominal categories (the strategies) all wear the same
slot-1 blue — bar length carries the comparison, never a value-ramp on
nominal bars; hairline solid grid; values direct-labeled at bar tips.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

from agv_simulation.map_builder import build_map
from agv_simulation.aisles import (
    init_catalog, sku_weight, walk_time_seconds, SLOTTING_STRATEGIES,
)
from agv_simulation.constants import (
    LEFT_HWY_COL, RIGHT_HWY_COL, NORTH_HWY_ROW, EAST_HWY_ROW,
)

FIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       os.pardir, "results", "figures")

# Reference palette (dataviz skill): sequential blue ramp, chrome/ink tokens
SEQ_BLUE = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
            "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281",
            "#0d366b"]
SERIES_1 = "#2a78d6"   # categorical slot 1 — every nominal bar wears this
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

CMAP = LinearSegmentedColormap.from_list("seq_blue", SEQ_BLUE)


def _style_axes(ax):
    ax.set_facecolor(SURFACE)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)


def popularity_maps() -> str:
    """2x2 small multiples: every slot colored by its SKU's demand weight."""
    tiles = build_map()
    fig, axes = plt.subplots(2, 2, figsize=(13, 6.2), layout="constrained")
    fig.patch.set_facecolor(SURFACE)

    scatter = None
    for ax, slotting in zip(axes.flat, SLOTTING_STRATEGIES):
        cat = init_catalog(tiles, slotting=slotting)
        xs, ys, ws = [], [], []
        for sku, slot in cat.slots.items():
            face_off = -0.45 if slot.face == "N" else 0.45
            level_off = -0.18 if slot.level == 0 else 0.18
            xs.append(slot.x)
            ys.append(slot.run_row + face_off + level_off)
            ws.append(sku_weight(sku))
        scatter = ax.scatter(xs, ys, c=ws, cmap=CMAP, vmin=0.0, vmax=1.0,
                             s=3.5, marker="s", linewidths=0)

        # Context: the one-way highway ring (hairline) and the S stations
        ax.plot([LEFT_HWY_COL, RIGHT_HWY_COL, RIGHT_HWY_COL, LEFT_HWY_COL,
                 LEFT_HWY_COL],
                [NORTH_HWY_ROW, NORTH_HWY_ROW, EAST_HWY_ROW, EAST_HWY_ROW,
                 NORTH_HWY_ROW],
                color=BASELINE, linewidth=1.0, zorder=0)
        for sid, (sx, sy) in cat.station_pos.items():
            ax.plot(sx, sy, marker="s", markersize=5, color=INK_2,
                    markeredgecolor=SURFACE, markeredgewidth=1)
            ax.annotate(sid, (sx, sy), xytext=(0, 6),
                        textcoords="offset points", ha="center",
                        fontsize=7, color=INK_2)

        walk = cat.demand_weighted_walk_m()
        ax.set_title(f"{slotting} — {walk:.1f} m demand-weighted walk",
                     fontsize=10, color=INK, loc="left")
        ax.invert_yaxis()
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        _style_axes(ax)

    fig.suptitle("SKU placement by popularity, per slotting strategy",
                 fontsize=13, color=INK)
    cbar = fig.colorbar(scatter, ax=axes, shrink=0.5, pad=0.02, aspect=30)
    cbar.set_label("SKU demand weight (1 = hottest)", fontsize=8, color=INK_2)
    cbar.ax.tick_params(colors=MUTED, labelsize=7)
    cbar.outline.set_visible(False)

    os.makedirs(FIG_DIR, exist_ok=True)
    path = os.path.join(FIG_DIR, "slotting_popularity_maps.png")
    fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return path


def walk_time_bars() -> str:
    """Bar chart: demand-weighted walk per pick, one bar per strategy.

    Nominal categories -> every bar wears series-1 blue (bar length is the
    comparison; a value-ramp here would double-encode it)."""
    tiles = build_map()
    walks = {}
    for slotting in SLOTTING_STRATEGIES:
        cat = init_catalog(tiles, slotting=slotting)
        walks[slotting] = cat.demand_weighted_walk_m()

    order = sorted(walks, key=walks.get)  # best (shortest) on top
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    fig.patch.set_facecolor(SURFACE)
    _style_axes(ax)

    ypos = range(len(order))
    values = [walks[s] for s in order]
    ax.barh(ypos, values, height=0.34, color=SERIES_1, zorder=3)
    ax.set_yticks(list(ypos), labels=order, fontsize=9)
    ax.tick_params(axis="y", colors=INK_2)
    ax.invert_yaxis()

    for y, s in zip(ypos, order):
        secs = walk_time_seconds(walks[s])
        ax.annotate(f"{walks[s]:.1f} m  ({secs:.0f} s/pick)",
                    (walks[s], y), xytext=(6, 0),
                    textcoords="offset points", va="center",
                    fontsize=9, color=INK)

    ax.xaxis.grid(True, color=GRID, linewidth=1.0, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xlabel("demand-weighted one-way walk per line (m)",
                  fontsize=9, color=INK_2)
    ax.set_xlim(0, max(values) * 1.28)
    ax.set_title("Picker walk per line, by slotting strategy",
                 fontsize=12, color=INK, loc="left", pad=12)

    os.makedirs(FIG_DIR, exist_ok=True)
    path = os.path.join(FIG_DIR, "walk_time_by_slotting.png")
    fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return path


if __name__ == "__main__":
    print(popularity_maps())
    print(walk_time_bars())
