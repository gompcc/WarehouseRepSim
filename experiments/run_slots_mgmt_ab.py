"""A/B: extra pick slots x picker management (2x2 factorial), run at both
the classic (23,52) and optimal (16,50) highway layouts.

3h sims (equilibrium is ~45 min, so >2h of settled signal) x seeds 41-43.
Worker PROCESSES because run_headless swaps module singletons. Appends a
table to results/slots_mgmt_ab.md.

Usage: ./venv/bin/python experiments/run_slots_mgmt_ab.py
"""

from __future__ import annotations

import datetime
import itertools
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agv_simulation import run_headless  # noqa: E402

SEEDS = (41, 42, 43)
DURATION = 10800.0
WORKERS = 6
HIGHWAYS = ((23, 52), (16, 50))
RESULTS_MD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "results", "slots_mgmt_ab.md",
)


def one_run(args) -> dict:
    highway, extra, mgmt, seed = args
    r = run_headless(
        sim_duration=DURATION, seed=seed, highway=highway,
        extra_slots=extra, picker_management=mgmt,
        export=False, snapshot_interval=0.0, log_level="ERROR",
    )
    ps = r["picker_stats"]
    return {
        "highway": highway, "extra": extra, "mgmt": mgmt, "seed": seed,
        "orders_hr": r["orders_per_hour"],
        "picks_hr": ps["picks_done"] / (DURATION / 3600.0),
        "pickers_final": 9 + ps["managed_hires"] - ps["managed_releases"],
        "lines_per_picker_hr": ps["lines_per_picker_hr"],
        "stuck": r["stuck_report"]["stuck_events"],
    }


def main() -> None:
    jobs = [
        (hw, extra, mgmt, seed)
        for hw in HIGHWAYS
        for extra, mgmt in itertools.product((False, True), repeat=2)
        for seed in SEEDS
    ]
    print(f"Running {len(jobs)} sims (3h each, {WORKERS} procs)")
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(one_run, j): j for j in jobs}
        for fut in as_completed(futures):
            row = fut.result()
            rows.append(row)
            print(
                f"  hwy={row['highway']} extra={int(row['extra'])}"
                f" mgmt={int(row['mgmt'])} seed={row['seed']}"
                f"  {row['orders_hr']:5.1f} orders/hr"
                f"  {row['picks_hr']:6.0f} picks/hr"
                f"  {row['pickers_final']:>2} pickers"
                f"  [{len(rows)}/{len(jobs)}]",
                flush=True,
            )

    grouped: dict[tuple, list[dict]] = {}
    for row in rows:
        grouped.setdefault(
            (row["highway"], row["extra"], row["mgmt"]), [],
        ).append(row)

    def mean(key, rs):
        return sum(r[key] for r in rs) / len(rs)

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"\n## Extra slots x picker management A/B — {stamp}\n",
        f"3h sims x seeds {SEEDS}, 10 AGVs / 25 carts, sequential "
        f"slotting, baseline dispatch, static picker strategy.\n",
        "| highway | extra slots | picker mgmt | orders/hr | picks/hr "
        "| pickers (end) | lines/picker/hr |",
        "|---------|-------------|-------------|-----------|----------"
        "|---------------|-----------------|",
    ]
    print("\nMEANS over seeds:")
    for key in sorted(grouped):
        hw, extra, mgmt = key
        rs = grouped[key]
        line = (
            f"| {hw} | {'ON' if extra else 'off'} | {'ON' if mgmt else 'off'} "
            f"| {mean('orders_hr', rs):.1f} | {mean('picks_hr', rs):.0f} "
            f"| {mean('pickers_final', rs):.1f} "
            f"| {mean('lines_per_picker_hr', rs):.0f} |"
        )
        lines.append(line)
        print(
            f"  hwy={hw} extra={'ON ' if extra else 'off'}"
            f" mgmt={'ON ' if mgmt else 'off'}"
            f"  {mean('orders_hr', rs):5.1f} orders/hr"
            f"  {mean('picks_hr', rs):6.0f} picks/hr"
            f"  {mean('pickers_final', rs):4.1f} pickers"
            f"  {mean('lines_per_picker_hr', rs):3.0f} l/p/hr"
        )
    with open(RESULTS_MD, "a") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nAppended to {RESULTS_MD}")


if __name__ == "__main__":
    main()
