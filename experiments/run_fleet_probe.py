"""Fleet probe for the winning policy stack (2026-07-29).

Batched release moved the constraint to AGV transport (agv_util
0.88-0.96 at the 10 AGV / 25 cart default while pickers idle at ~50%
— results/batch_release_ab.md), so the fleet tuned for the old
station-bound regime is stale. Stage 1 screens an AGV x cart grid at
2h seed 42 under mgmt + extra slots + batched release at the swept
optimal pillars; stage 2 confirms the top CONFIRM_TOP at 2h x 3 seeds.

Workers are separate PROCESSES (run_headless swaps module singletons).
Appends both tables to results/fleet_probe.md.

Usage:  ./venv/bin/python experiments/run_fleet_probe.py [--quick]
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agv_simulation import run_headless  # noqa: E402
from agv_simulation.layout import OPTIMAL_HIGHWAY  # noqa: E402

AGV_GRID = (10, 12, 14, 16, 18)
CART_GRID = (25, 30, 35)
CONFIRM_TOP = 3
CONFIRM_SEEDS = (41, 42, 43)
WORKERS = 6
POLICY_KWARGS = dict(
    picker_management=True, extra_slots=True, batch_release=True,
)
RESULTS_MD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "results", "fleet_probe.md",
)


def one_run(args: tuple[int, int, int, float]) -> dict:
    agvs, carts, seed, duration = args
    r = run_headless(
        num_agvs=agvs, num_carts=carts, sim_duration=duration, seed=seed,
        highway=OPTIMAL_HIGHWAY, export=False, snapshot_interval=0.0,
        log_level="ERROR", **POLICY_KWARGS,
    )
    return {
        "agvs": agvs, "carts": carts, "seed": seed,
        "orders_per_hour": r["orders_per_hour"],
        "picks_hr": r["picker_stats"]["picks_done"] / (duration / 3600.0),
        "blocked": r["agv_blocked_fraction"],
        "agv_util": r["agv_utilization"],
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
                f"  {row['agvs']:>2}A/{row['carts']}C seed={row['seed']}"
                f"  {row['orders_per_hour']:5.1f} orders/hr"
                f"  {row['picks_hr']:6.0f} picks/hr"
                f"  util {row['agv_util']:.0%}"
                f"  blocked {row['blocked']:.0%}"
                f"  [{len(done)}/{len(jobs)}]",
                flush=True,
            )
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    opts = ap.parse_args()
    duration = 3600.0 if opts.quick else 7200.0

    grid = [(a, c) for a in AGV_GRID for c in CART_GRID]
    print(f"Stage 1: screening {len(grid)} fleets at L{OPTIMAL_HIGHWAY[0]}/"
          f"R{OPTIMAL_HIGHWAY[1]} ({duration / 3600.0:.1f}h, seed 42, "
          f"mgmt+extra+batch, {WORKERS} procs)")
    screen = run_pool([(a, c, 42, duration) for a, c in grid])
    screen.sort(key=lambda d: -d["orders_per_hour"])

    top = screen[:CONFIRM_TOP]
    print(f"\nStage 2: confirming top {len(top)} at seeds {CONFIRM_SEEDS}")
    confirm = run_pool([
        (d["agvs"], d["carts"], s, duration)
        for d in top for s in CONFIRM_SEEDS if s != 42
    ])
    confirm += [d for d in top]  # reuse the seed-42 screen rows

    by_fleet: dict[tuple[int, int], list[dict]] = {}
    for row in confirm:
        by_fleet.setdefault((row["agvs"], row["carts"]), []).append(row)
    ranked = []
    for (a, c), rows in by_fleet.items():
        rates = [x["orders_per_hour"] for x in rows]
        ranked.append({
            "agvs": a, "carts": c,
            "mean": sum(rates) / len(rates),
            "min": min(rates), "max": max(rates),
            "picks_hr": sum(x["picks_hr"] for x in rows) / len(rows),
        })
    ranked.sort(key=lambda d: -d["mean"])

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(RESULTS_MD, "a") as f:
        f.write(f"\n## Fleet probe — {stamp}\n\n")
        f.write(f"L{OPTIMAL_HIGHWAY[0]}/R{OPTIMAL_HIGHWAY[1]}, "
                f"mgmt + extra slots + batched release, flat demand, "
                f"{duration / 3600.0:.1f}h sims. Screen seed 42; confirm "
                f"top {CONFIRM_TOP} x seeds {CONFIRM_SEEDS}.\n\n")
        f.write("### Screen (seed 42)\n\n")
        f.write("| AGVs | carts | orders/hr | picks/hr | util | blocked |\n")
        f.write("|------|-------|-----------|----------|------|--------|\n")
        for d in screen:
            f.write(f"| {d['agvs']} | {d['carts']} "
                    f"| {d['orders_per_hour']:.1f} | {d['picks_hr']:.0f} "
                    f"| {d['agv_util']:.0%} | {d['blocked']:.0%} |\n")
        f.write("\n### Confirmed (mean over seeds)\n\n")
        f.write("| AGVs | carts | orders/hr mean | min-max | picks/hr |\n")
        f.write("|------|-------|----------------|---------|----------|\n")
        for d in ranked:
            f.write(f"| {d['agvs']} | {d['carts']} | {d['mean']:.1f} "
                    f"| {d['min']:.1f}-{d['max']:.1f} "
                    f"| {d['picks_hr']:.0f} |\n")

    print(f"\nResults appended to {RESULTS_MD}\n")
    print("CONFIRMED RANKING (orders/hr, mean over seeds):")
    for d in ranked:
        print(f"  {d['agvs']:>2}A/{d['carts']}C  {d['mean']:5.1f}"
              f"  ({d['min']:.1f}-{d['max']:.1f})"
              f"  {d['picks_hr']:.0f} picks/hr")


if __name__ == "__main__":
    main()
