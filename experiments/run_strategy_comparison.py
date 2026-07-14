"""Controlled A/B comparison of dispatch strategy modules.

Runs every toggle combination against identical seeded order streams
(order N is byte-identical across all runs of a seed), 8h sim each,
and writes a markdown comparison table to results/strategy_comparison.md.

Usage:
    ./venv/bin/python experiments/run_strategy_comparison.py
    ./venv/bin/python experiments/run_strategy_comparison.py --quick   # 2h sims
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
SEEDS = [11, 42, 77]
# (agvs, carts): station-saturated, transport-bound, and low-WIP regimes
CONFIGS = [(14, 25), (10, 25), (10, 15)]


def run_one(task: tuple[dict, int, float, int, int]) -> dict:
    strategies, seed, duration, num_agvs, num_carts = task
    from agv_simulation import run_headless

    r = run_headless(
        num_agvs=num_agvs,
        num_carts=num_carts,
        sim_duration=duration,
        seed=seed,
        strategies=strategies,
        log_level="ERROR",
    )
    return {
        "combo": combo_name(strategies),
        "config": f"{num_agvs}/{num_carts}",
        "seed": seed,
        "orders_per_hour": r["orders_per_hour"],
        "completed": r["completed_orders"],
        "avg_cycle": r["avg_cycle_time"],
        "stuck": r["stuck_report"]["stuck_events"],
        "blocked": r["agv_blocked_fraction"],
    }


def combo_name(strategies: dict) -> str:
    on = [SHORT[a] for a in STRATEGY_ATTRS if strategies.get(a)]
    return "+".join(on) if on else "baseline"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="2h sims instead of 8h")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    duration = 7200.0 if args.quick else 28800.0

    combos = [
        {attr: bool(bits & (1 << i)) for i, attr in enumerate(STRATEGY_ATTRS)}
        for bits in range(2 ** len(STRATEGY_ATTRS))
    ]
    tasks = [
        (c, s, duration, agvs, carts)
        for (agvs, carts), c, s in itertools.product(CONFIGS, combos, SEEDS)
    ]
    print(f"{len(tasks)} runs ({len(CONFIGS)} configs x {len(combos)} combos x "
          f"{len(SEEDS)} seeds, {duration / 3600:.0f}h sim)")

    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, res in enumerate(pool.map(run_one, tasks), 1):
            print(f"  [{i}/{len(tasks)}] {res['config']:6s} {res['combo']:16s} "
                  f"seed={res['seed']:2d} -> {res['orders_per_hour']:.1f} o/hr",
                  flush=True)
            results.append(res)

    def mean(vals: list[float]) -> float:
        return sum(vals) / len(vals)

    lines = [
        f"\n## Strategy comparison — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        f"{duration / 3600:.0f}h sims, seeds {SEEDS} "
        f"(identical order streams per seed)\n",
    ]
    for agvs, carts in CONFIGS:
        cfg = f"{agvs}/{carts}"
        by_combo: dict[str, list[dict]] = {}
        for res in results:
            if res["config"] == cfg:
                by_combo.setdefault(res["combo"], []).append(res)
        baseline_ophr = mean([r["orders_per_hour"] for r in by_combo["baseline"]])

        rows = []
        for combo, rs in by_combo.items():
            ophr = [r["orders_per_hour"] for r in rs]
            rows.append({
                "combo": combo,
                "mean": mean(ophr),
                "min": min(ophr),
                "max": max(ophr),
                "delta": (mean(ophr) - baseline_ophr) / baseline_ophr * 100,
                "cycle": mean([r["avg_cycle"] for r in rs]) / 60.0,
                "stuck": mean([r["stuck"] for r in rs]),
                "blocked": mean([r["blocked"] for r in rs]) * 100,
            })
        rows.sort(key=lambda r: -r["mean"])

        lines += [
            f"\n### {agvs} AGVs / {carts} carts\n\n",
            "| Strategies | Orders/hr (mean) | Range | vs baseline | Avg cycle | Stuck | Blocked% |\n",
            "|---|---|---|---|---|---|---|\n",
        ]
        for r in rows:
            lines.append(
                f"| {r['combo']} | **{r['mean']:.1f}** | {r['min']:.1f}–{r['max']:.1f} "
                f"| {r['delta']:+.1f}% | {r['cycle']:.1f}m | {r['stuck']:.0f} "
                f"| {r['blocked']:.1f} |\n"
            )

    os.makedirs("results", exist_ok=True)
    with open("results/strategy_comparison.md", "a") as f:
        f.writelines(lines)
    print("".join(lines))
    print("Appended to results/strategy_comparison.md")


if __name__ == "__main__":
    main()
