"""Decision figures from the experiment matrix (results/runs/matrix_rows.json).

Usage: ./venv/bin/python experiments/plot_matrix.py
Writes 3 PNGs to results/figures/ (plus rerun plot_placement.py for the
walk-time chart). Styling per the dataviz method: single series-blue for
nominal bars, min–max seed ranges as error bars, hairline grid.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SERIES_1 = "#2a78d6"
SERIES_2 = "#1baf7a"
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
FIG_DIR = os.path.join(BASE, "results", "figures")
ROWS = json.load(open(os.path.join(BASE, "results", "runs", "matrix_rows.json")))


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=1.0)
    ax.set_axisbelow(True)


def arm_rows(slotting, pstrat, dispatch):
    return [r for r in ROWS if (r["slotting"], r["picker_strategy"],
                                r["dispatch"]) == (slotting, pstrat, dispatch)]


def stats(rows, key="steady_orders_hr"):
    vals = [r[key] for r in rows]
    return sum(vals) / len(vals), min(vals), max(vals)


def bars(ax, labels, arms, color=SERIES_1, key="steady_orders_hr"):
    means, lo_err, hi_err = [], [], []
    for a in arms:
        m, lo, hi = stats(arm_rows(*a), key)
        means.append(m)
        lo_err.append(m - lo)
        hi_err.append(hi - m)
    x = range(len(labels))
    ax.bar(x, means, width=0.42, color=color, zorder=3)
    ax.errorbar(x, means, yerr=[lo_err, hi_err], fmt="none",
                ecolor=INK_2, elinewidth=1.2, capsize=4, zorder=4)
    ax.set_xticks(list(x), labels, fontsize=9, color=INK_2)
    for xi, m in zip(x, means):
        ax.annotate(f"{m:.1f}", (xi, m), xytext=(0, 6),
                    textcoords="offset points", ha="center",
                    fontsize=10, color=INK)
    return means


def fig_slotting():
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    bars(ax, ["sequential", "aisle_proximal", "fibonacci"],
         [("sequential", "static", "baseline"),
          ("aisle_proximal", "static", "baseline"),
          ("fibonacci", "static", "baseline")])
    ax.set_ylabel("steady orders/hr", fontsize=9, color=INK_2)
    ax.set_title("Slotting arms — 8h, 5 paired seeds, static pickers"
                 " (error bars: seed min–max)",
                 fontsize=11, color=INK, loc="left", pad=12)
    fig.savefig(os.path.join(FIG_DIR, "matrix_slotting.png"),
                dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def fig_pickers():
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    labels = ["sequential", "fibonacci"]
    x = range(len(labels))
    w = 0.32
    for off, (pstrat, color, name) in enumerate(
            [("static", SERIES_1, "static"), ("dynamic", SERIES_2, "dynamic")]):
        means, lo_e, hi_e = [], [], []
        for s in labels:
            m, lo, hi = stats(arm_rows(s, pstrat, "baseline"))
            means.append(m)
            lo_e.append(m - lo)
            hi_e.append(hi - m)
        xs = [xi + (off - 0.5) * (w + 0.04) for xi in x]
        ax.bar(xs, means, width=w, color=color, zorder=3, label=name)
        ax.errorbar(xs, means, yerr=[lo_e, hi_e], fmt="none",
                    ecolor=INK_2, elinewidth=1.2, capsize=4, zorder=4)
        for xi, m in zip(xs, means):
            ax.annotate(f"{m:.1f}", (xi, m), xytext=(0, 6),
                        textcoords="offset points", ha="center",
                        fontsize=9, color=INK)
    ax.set_xticks(list(x), labels, fontsize=9, color=INK_2)
    ax.set_ylabel("steady orders/hr", fontsize=9, color=INK_2)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK_2)
    ax.set_title("Picker strategy × slotting — dynamic roam-within-side"
                 " (error bars: seed min–max)",
                 fontsize=11, color=INK, loc="left", pad=12)
    fig.savefig(os.path.join(FIG_DIR, "matrix_pickers.png"),
                dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def fig_dispatch():
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    bars(ax, ["baseline", "ETA", "Hungarian", "ETA+Hungarian"],
         [("fibonacci", "static", "baseline"),
          ("fibonacci", "static", "eta_reservations"),
          ("fibonacci", "static", "global_assignment"),
          ("fibonacci", "static", "eta_reservations+global_assignment")])
    ax.set_ylabel("steady orders/hr", fontsize=9, color=INK_2)
    ax.set_title("Dispatch strategies on fibonacci/static — none clears the"
                 " +3% adoption bar; Hungarian alone is unstable",
                 fontsize=11, color=INK, loc="left", pad=12)
    fig.savefig(os.path.join(FIG_DIR, "matrix_dispatch.png"),
                dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(FIG_DIR, exist_ok=True)
    fig_slotting()
    fig_pickers()
    fig_dispatch()
    print("wrote matrix_slotting.png, matrix_pickers.png, matrix_dispatch.png")
