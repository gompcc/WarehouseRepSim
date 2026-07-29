"""Two-stage sweep over highway pillar positions (dynamic-highway branch).

Stage 1 (screen): every valid (left, right) on a step-3 grid plus the
default (23, 52), 1h sims, seed 42 — one cheap deterministic look at each
geometry against the identical order stream.

Stage 2 (confirm): the top CONFIRM_TOP screen candidates re-run at 2h x 3
seeds; ranking is by mean orders/hr with the spread reported.

Workers are separate PROCESSES: run_headless swaps module singletons
(layout, catalog, order seed), so in-process concurrency would race.
Appends both tables to results/highway_sweep.md.

Usage:  ./venv/bin/python experiments/run_highway_sweep.py [--quick]
        (--quick: 30min screen / 1h confirm, for smoke-testing the script)
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agv_simulation import run_headless  # noqa: E402
from agv_simulation.layout import (  # noqa: E402
    LEFT_COL_MIN, MIN_PILLAR_GAP, RIGHT_COL_MAX,
)

GRID_STEP = 3
CONFIRM_TOP = 5
CONFIRM_SEEDS = (41, 42, 43)
WORKERS = 6   # leave headroom for an interactive GUI session
# The policy stack every layout is judged under. Re-swept 2026-07-29:
# the original sweep ran bare-baseline under OLD popularity demand (and
# rows L>=31 hit the since-fixed depot-gridlock bug) — layout optima are
# CONDITIONAL on staffing policy (results/slots_mgmt_ab.md), so the grid
# must be scored under the winning stack, now mgmt+extra+batched release
# (results/batch_release_ab.md).
POLICY_KWARGS = dict(
    picker_management=True, extra_slots=True, batch_release=True,
)
POLICY_LABEL = "picker mgmt + extra slots + batched release"
RESULTS_MD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "results", "highway_sweep.md",
)


def candidate_grid() -> list[tuple[int, int]]:
    lefts = range(LEFT_COL_MIN, 36, GRID_STEP)          # 16..34
    rights = range(38, RIGHT_COL_MAX + 1, GRID_STEP)    # 38..68
    pairs = [
        (l, r) for l in lefts
        for r in [*rights, RIGHT_COL_MAX]
        if r - l >= MIN_PILLAR_GAP
    ]
    pairs.append((23, 52))  # the classic layout as the reference row
    return sorted(set(pairs))


def one_run(args: tuple[int, int, int, float]) -> dict:
    left, right, seed, duration = args
    r = run_headless(
        sim_duration=duration, seed=seed, highway=(left, right),
        export=False, snapshot_interval=0.0, log_level="ERROR",
        **POLICY_KWARGS,
    )
    return {
        "left": left, "right": right, "seed": seed,
        "orders_per_hour": r["orders_per_hour"],
        "picks_hr": r["picker_stats"]["picks_done"] / (duration / 3600.0),
        "avg_cycle": r["avg_cycle_time"],
        "blocked": r["agv_blocked_fraction"],
        "stuck": r["stuck_report"]["stuck_events"],
    }


def run_pool(jobs: list[tuple[int, int, int, float]]) -> list[dict]:
    done: list[dict] = []
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(one_run, j): j for j in jobs}
        for fut in as_completed(futures):
            row = fut.result()
            done.append(row)
            print(
                f"  L={row['left']:>2} R={row['right']:>2} seed={row['seed']}"
                f"  {row['orders_per_hour']:5.1f} orders/hr"
                f"  {row['picks_hr']:6.0f} picks/hr"
                f"  blocked {row['blocked']:.0%}  stuck {row['stuck']}"
                f"  [{len(done)}/{len(jobs)}]",
                flush=True,
            )
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    opts = ap.parse_args()
    screen_h = 1800.0 if opts.quick else 3600.0
    confirm_h = 3600.0 if opts.quick else 7200.0

    grid = candidate_grid()
    print(f"Stage 1: screening {len(grid)} pillar layouts "
          f"({screen_h / 3600.0:.1f}h sims, seed 42, {WORKERS} procs)")
    screen = run_pool([(l, r, 42, screen_h) for l, r in grid])
    screen.sort(key=lambda d: -d["orders_per_hour"])

    top = screen[:CONFIRM_TOP]
    print(f"\nStage 2: confirming top {len(top)} at "
          f"{confirm_h / 3600.0:.1f}h x seeds {CONFIRM_SEEDS}")
    confirm = run_pool([
        (d["left"], d["right"], s, confirm_h)
        for d in top for s in CONFIRM_SEEDS
    ])

    by_pair: dict[tuple[int, int], list[dict]] = {}
    for row in confirm:
        by_pair.setdefault((row["left"], row["right"]), []).append(row)
    ranked = []
    for (l, r), rows in by_pair.items():
        rates = [x["orders_per_hour"] for x in rows]
        mean = sum(rates) / len(rates)
        ranked.append({
            "left": l, "right": r, "mean": mean,
            "min": min(rates), "max": max(rates),
            "picks_hr": sum(x["picks_hr"] for x in rows) / len(rows),
        })
    ranked.sort(key=lambda d: -d["mean"])

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(RESULTS_MD, "a") as f:
        f.write(f"\n## Highway pillar sweep — {stamp}\n\n")
        f.write(f"Screen: {len(grid)} layouts x {screen_h / 3600.0:.1f}h, "
                f"seed 42. Confirm: top {CONFIRM_TOP} x "
                f"{confirm_h / 3600.0:.1f}h x seeds {CONFIRM_SEEDS}. "
                f"10 AGVs / 25 carts, sequential slotting, baseline "
                f"dispatch, {POLICY_LABEL} (flat demand).\n\n")
        f.write("### Screen (top 15 of grid, seed 42)\n\n")
        f.write("| L | R | orders/hr | picks/hr | blocked | stuck |\n")
        f.write("|---|---|-----------|----------|---------|-------|\n")
        for d in screen[:15]:
            f.write(f"| {d['left']} | {d['right']} "
                    f"| {d['orders_per_hour']:.1f} | {d['picks_hr']:.0f} "
                    f"| {d['blocked']:.0%} | {d['stuck']} |\n")
        f.write("\n### Confirmed ranking (mean over seeds)\n\n")
        f.write("| L | R | orders/hr mean | min-max | picks/hr |\n")
        f.write("|---|---|----------------|---------|----------|\n")
        for d in ranked:
            f.write(f"| {d['left']} | {d['right']} | {d['mean']:.1f} "
                    f"| {d['min']:.1f}-{d['max']:.1f} "
                    f"| {d['picks_hr']:.0f} |\n")

    print(f"\nResults appended to {RESULTS_MD}\n")
    print("CONFIRMED RANKING (orders/hr, mean over seeds):")
    for d in ranked:
        print(f"  L={d['left']:>2} R={d['right']:>2}  "
              f"{d['mean']:5.1f}  ({d['min']:.1f}-{d['max']:.1f})")
    ref = next((d for d in screen if (d['left'], d['right']) == (23, 52)), None)
    if ref:
        print(f"  reference (23,52) screen: {ref['orders_per_hour']:.1f}")


if __name__ == "__main__":
    main()
