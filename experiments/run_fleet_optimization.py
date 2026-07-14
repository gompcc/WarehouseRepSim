"""Per-strategy fleet optimization: find each combo's own (AGVs, carts) optimum.

Comparing every strategy combo at one fixed fleet answers "which policy is
best at baseline's operating point". The fairer — and operationally useful —
question is "which policy is best at *its own* optimum, and what fleet does
it want?" (dispatch policy changes congestion behavior, so the throughput-
maximizing fleet size differs per policy).

Two-stage search per combo:
  Stage 1: coarse AGVs x carts grid, 1 seed (screening).
  Stage 2: each combo's top-K stage-1 configs re-run on the remaining seeds;
           winner = best 3-seed mean.

Usage:
    ./venv/bin/python experiments/run_fleet_optimization.py
    ./venv/bin/python experiments/run_fleet_optimization.py --quick  # 2h sims
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STRATEGY_ATTRS = ["eta_reservations", "global_assignment"]
SHORT = {"eta_reservations": "ETA", "global_assignment": "HUN"}

SCREEN_SEED = 42
CONFIRM_SEEDS = [11, 77]          # stage 2 adds these to the screening seed
AGV_GRID = [10, 12, 14, 16, 18]
CART_GRID = [15, 20, 25, 30]
TOP_K = 3                          # configs per combo advancing to stage 2


def combo_name(strategies: dict) -> str:
    on = [SHORT[a] for a in STRATEGY_ATTRS if strategies.get(a)]
    return "+".join(on) if on else "baseline"


def all_combos() -> list[dict]:
    return [
        {attr: bool(bits & (1 << i)) for i, attr in enumerate(STRATEGY_ATTRS)}
        for bits in range(2 ** len(STRATEGY_ATTRS))
    ]


def run_one(task: tuple[dict, int, int, int, float]) -> dict:
    strategies, seed, num_agvs, num_carts, duration = task
    from agv_simulation import run_headless

    r = run_headless(
        num_agvs=num_agvs,
        num_carts=num_carts,
        sim_duration=duration,
        seed=seed,
        strategies=strategies,
        log_level="ERROR",
        export=False,
    )
    return {
        "combo": combo_name(strategies),
        "strategies": strategies,
        "seed": seed,
        "agvs": num_agvs,
        "carts": num_carts,
        "orders_per_hour": r["orders_per_hour"],
        "blocked": r["agv_blocked_fraction"],
    }


def mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="2h sims instead of 8h")
    parser.add_argument("--workers", type=int, default=7)
    args = parser.parse_args()
    duration = 7200.0 if args.quick else 28800.0

    combos = all_combos()

    # ------------------------------------------------------------------
    # Stage 1: coarse grid screening (1 seed)
    # ------------------------------------------------------------------
    stage1 = [
        (c, SCREEN_SEED, agvs, carts, duration)
        for c, agvs, carts in itertools.product(combos, AGV_GRID, CART_GRID)
    ]
    print(f"Stage 1: {len(stage1)} screening runs "
          f"({len(combos)} combos x {len(AGV_GRID)}x{len(CART_GRID)} fleet grid, "
          f"seed {SCREEN_SEED}, {duration / 3600:.0f}h sims)")

    screen: dict[str, list[dict]] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, res in enumerate(pool.map(run_one, stage1), 1):
            screen.setdefault(res["combo"], []).append(res)
            print(f"  [{i}/{len(stage1)}] {res['combo']:16s} "
                  f"{res['agvs']:2d}/{res['carts']:2d} -> "
                  f"{res['orders_per_hour']:.1f} o/hr", flush=True)

    # ------------------------------------------------------------------
    # Stage 2: confirm each combo's top-K configs on the remaining seeds
    # ------------------------------------------------------------------
    finalists: list[tuple[dict, int, int, int, float]] = []
    finalist_meta: dict[str, list[tuple[int, int]]] = {}
    for combo in combos:
        name = combo_name(combo)
        top = sorted(screen[name], key=lambda r: -r["orders_per_hour"])[:TOP_K]
        finalist_meta[name] = [(r["agvs"], r["carts"]) for r in top]
        for r in top:
            for seed in CONFIRM_SEEDS:
                finalists.append((combo, seed, r["agvs"], r["carts"], duration))

    print(f"\nStage 2: {len(finalists)} confirmation runs "
          f"(top {TOP_K} configs per combo x seeds {CONFIRM_SEEDS})")
    confirm: dict[tuple[str, int, int], list[float]] = {}
    # Seed the means with the stage-1 screening result
    for name, cfgs in finalist_meta.items():
        for agvs, carts in cfgs:
            s1 = next(r for r in screen[name]
                      if r["agvs"] == agvs and r["carts"] == carts)
            confirm[(name, agvs, carts)] = [s1["orders_per_hour"]]

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, res in enumerate(pool.map(run_one, finalists), 1):
            key = (res["combo"], res["agvs"], res["carts"])
            confirm[key].append(res["orders_per_hour"])
            print(f"  [{i}/{len(finalists)}] {res['combo']:16s} "
                  f"{res['agvs']:2d}/{res['carts']:2d} seed={res['seed']:2d} -> "
                  f"{res['orders_per_hour']:.1f} o/hr", flush=True)

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    lines = [
        f"\n## Fleet optimization per strategy — "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        f"{duration / 3600:.0f}h sims. Stage 1: {len(AGV_GRID)}x{len(CART_GRID)} "
        f"fleet grid (AGVs {AGV_GRID}, carts {CART_GRID}), seed {SCREEN_SEED}. "
        f"Stage 2: top {TOP_K} per combo confirmed on seeds "
        f"{[SCREEN_SEED] + CONFIRM_SEEDS} (3-seed means below).\n\n",
        "| Strategies | Best fleet (AGVs/carts) | Orders/hr @ own optimum "
        "| Runners-up (3-seed mean) |\n",
        "|---|---|---|---|\n",
    ]
    summary_rows = []
    for combo in combos:
        name = combo_name(combo)
        ranked = sorted(
            ((cfg, mean(confirm[(name, *cfg)])) for cfg in finalist_meta[name]),
            key=lambda kv: -kv[1],
        )
        (best_cfg, best_mean), runners = ranked[0], ranked[1:]
        summary_rows.append((name, best_cfg, best_mean))
        runner_txt = ", ".join(
            f"{a}/{c}: {m:.1f}" for (a, c), m in runners
        )
        lines.append(
            f"| {name} | **{best_cfg[0]}/{best_cfg[1]}** | **{best_mean:.1f}** "
            f"| {runner_txt} |\n"
        )

    base_best = next(m for n, _, m in summary_rows if n == "baseline")
    lines.append("\nAt-own-optimum comparison vs baseline-at-its-optimum "
                 f"({base_best:.1f} o/hr):\n\n")
    for name, cfg, m in sorted(summary_rows, key=lambda r: -r[2]):
        delta = (m - base_best) / base_best * 100
        lines.append(f"- **{name}** @ {cfg[0]}/{cfg[1]}: {m:.1f} o/hr ({delta:+.1f}%)\n")

    # Full stage-1 grid per combo (screening data, 1 seed) for the record
    lines.append("\n<details><summary>Stage-1 screening grids (seed "
                 f"{SCREEN_SEED}, single runs)</summary>\n\n")
    for combo in combos:
        name = combo_name(combo)
        lines.append(f"\n**{name}** (orders/hr)\n\n")
        lines.append("| AGVs \\ carts | " + " | ".join(map(str, CART_GRID)) + " |\n")
        lines.append("|---" * (len(CART_GRID) + 1) + "|\n")
        for agvs in AGV_GRID:
            cells = []
            for carts in CART_GRID:
                r = next(x for x in screen[name]
                         if x["agvs"] == agvs and x["carts"] == carts)
                cells.append(f"{r['orders_per_hour']:.1f}")
            lines.append(f"| {agvs} | " + " | ".join(cells) + " |\n")
    lines.append("\n</details>\n")

    os.makedirs("results", exist_ok=True)
    with open("results/fleet_optimization.md", "a") as f:
        f.writelines(lines)
    print("".join(lines))
    print("Appended to results/fleet_optimization.md")


if __name__ == "__main__":
    main()
