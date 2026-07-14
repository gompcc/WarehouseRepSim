"""One-off: does ETA beat the 89.5 o/hr record at 16 AGVs / 25 carts?"""

import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def go(args):
    strat, seed = args
    from agv_simulation import run_headless
    r = run_headless(num_agvs=16, num_carts=25, sim_duration=28800, seed=seed,
                     strategies=strat, log_level="ERROR")
    return (r["strategies"], seed, r["orders_per_hour"])


TASKS = [
    (s, seed)
    for s in [
        {},
        {"eta_reservations": True},
        {"eta_reservations": True, "global_assignment": True},
    ]
    for seed in [11, 42, 77]
]

if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=7) as pool:
        for strats, seed, ophr in pool.map(go, TASKS):
            name = "+".join(strats) or "baseline"
            print(f"16/25 {name:16s} seed={seed:2d} -> {ophr:.1f} o/hr", flush=True)
