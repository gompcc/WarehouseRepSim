"""The experiment matrix (EXPERIMENT_DESIGN.md, 2026-07-14 model).

Sections:
  A  — slotting arms: sequential / aisle_proximal / fibonacci, static
       pickers, baseline dispatch. 5 paired seeds.
  A2 — picker strategy: static vs dynamic × {sequential, aisle_proximal}.
       5 paired seeds (static cells shared with A).
  B  — dispatch: baseline / ETA / HUN / ETA+HUN on the best Section A arm,
       static pickers. 5 paired seeds.

All runs: 8 h, 10 AGVs / 25 carts, canonical order book (seeds = book
windows, paired across arms), export=False, per-run JSON in results/runs/.
Warm-up: completions with t > 1800 s over 7.5 h = steady orders/hr.

Usage:  ./venv/bin/python experiments/run_matrix.py [--workers N]
Writes results/experiment_matrix.md + results/runs/matrix_*.json.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SEEDS = (11, 42, 77, 101, 137)
FLEET = dict(num_agvs=10, num_carts=25)
RUNS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "results", "runs")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      os.pardir, "results", "experiment_matrix.md")


def one_run(args):
    (slotting, pstrat, strategies, seed) = args
    from agv_simulation import run_headless
    r = run_headless(
        seed=seed, export=False, log_level="ERROR",
        slotting=slotting, picker_strategy=pstrat, strategies=strategies,
        **FLEET,
    )
    warm = [t for t in r["order_completion_times"] if t > 1800.0]
    ps = r["picker_stats"]
    busy = [v["busy_fraction"] for v in ps["per_station"].values()]
    bmean = sum(busy) / len(busy)
    cv = ((sum((b - bmean) ** 2 for b in busy) / len(busy)) ** 0.5 / bmean
          if bmean else 0.0)
    return {
        "slotting": slotting,
        "picker_strategy": pstrat,
        "dispatch": "+".join(sorted(strategies)) if strategies else "baseline",
        "seed": seed,
        "steady_orders_hr": len(warm) / 7.5,
        "picks_hr": ps["picks_done"] / 8.0,
        "lines_per_picker_hr": ps["lines_per_picker_hr"],
        "picker_busy": ps["busy_fraction"],
        "busy_cv": cv,
        "walk_mean_s": ps["walk_mean_s"],
        "relocations": ps["relocations"],
        "agv_util": r["agv_utilization"],
        "cycle_min": r["avg_cycle_time"] / 60.0,
        "carts_left_early": ps["carts_left_early"],
        "teleports": r["stuck_report"]["teleport_events"],
        "stuck_events": r["stuck_report"]["stuck_events"],
    }


def cells():
    # Section A: 3 slotting arms, static, baseline dispatch
    for slotting in ("sequential", "aisle_proximal", "fibonacci"):
        for seed in SEEDS:
            yield (slotting, "static", None, seed)
    # Section A2: dynamic pickers on the worst-balanced arm (sequential)
    # and the best arm (fibonacci — per the seed-42 integration sweep)
    for slotting in ("sequential", "fibonacci"):
        for seed in SEEDS:
            yield (slotting, "dynamic", None, seed)
    # Section B: dispatch combos on fibonacci (best Section A arm per the
    # integration sweep), static pickers; baseline cell shared with A
    for strat in ({"eta_reservations": True},
                  {"global_assignment": True},
                  {"eta_reservations": True, "global_assignment": True}):
        for seed in SEEDS:
            yield ("fibonacci", "static", strat, seed)


def arm_key(row):
    return (row["slotting"], row["picker_strategy"], row["dispatch"])


def summarize(rows):
    arms: dict = {}
    for row in rows:
        arms.setdefault(arm_key(row), []).append(row)
    lines = [
        "# Experiment matrix — %d runs (8h, 10A/25C, order book, seeds %s)\n"
        % (len(rows), list(SEEDS)),
        "| Arm (slotting/pickers/dispatch) | Steady o/hr (min–max) | Picks/hr |"
        " Lines/picker/hr | Busy | Busy CV | AGV util | Validity |",
        "|---|---|---|---|---|---|---|---|",
    ]
    def mean(vals):
        return sum(vals) / len(vals)
    for key in sorted(arms):
        rs = arms[key]
        o = [r["steady_orders_hr"] for r in rs]
        bad = sum(r["teleports"] + r["carts_left_early"] for r in rs)
        lines.append(
            "| %s | **%.1f** (%.1f–%.1f) | %.0f | %.1f | %.0f%% | %.2f |"
            " %.0f%% | %s |" % (
                "/".join(key), mean(o), min(o), max(o),
                mean([r["picks_hr"] for r in rs]),
                mean([r["lines_per_picker_hr"] for r in rs]),
                mean([r["picker_busy"] for r in rs]) * 100,
                mean([r["busy_cv"] for r in rs]),
                mean([r["agv_util"] for r in rs]) * 100,
                "OK" if bad == 0 else f"{bad} bad",
            )
        )
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    todo = list(cells())
    print(f"{len(todo)} runs on {args.workers} workers")
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, row in enumerate(pool.map(one_run, todo), 1):
            rows.append(row)
            print(f"[{i}/{len(todo)}] {arm_key(row)} seed={row['seed']}"
                  f" -> {row['steady_orders_hr']:.1f} o/hr", flush=True)

    os.makedirs(RUNS_DIR, exist_ok=True)
    with open(os.path.join(RUNS_DIR, "matrix_rows.json"), "w") as f:
        json.dump(rows, f, indent=1)
    md = summarize(rows)
    with open(OUT_MD, "w") as f:
        f.write(md)
    print(md)
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
