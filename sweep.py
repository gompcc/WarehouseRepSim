#!/usr/bin/env python3
"""
Parameter sweep for AGV warehouse simulation.

Runs run_headless() across combinations of AGV and cart counts,
reports throughput metrics, and optionally writes CSV output.

Usage:
    python sweep.py
    python sweep.py --agvs 4,8 --carts 8,16 --duration 1800
    python sweep.py --csv results.csv --parallel
"""
import sys
import types
import argparse
import csv
import multiprocessing
import os

# ── Pygame stub (same pattern as test_collision_avoidance.py) ──
_pg = types.ModuleType("pygame")
_pg.init = lambda: None
_pg.quit = lambda: None
_pg.display = types.ModuleType("pygame.display")
_pg.display.set_mode = lambda *a, **k: None
_pg.display.set_caption = lambda *a, **k: None
_pg.font = types.ModuleType("pygame.font")
_pg.font.SysFont = lambda *a, **k: None
sys.modules["pygame"] = _pg
sys.modules["pygame.display"] = _pg.display
sys.modules["pygame.font"] = _pg.font

from agv_simulation import run_headless


def _init_worker():
    """Pool initializer: ensure pygame is stubbed in each forked process."""
    _pg2 = types.ModuleType("pygame")
    _pg2.init = lambda: None
    _pg2.quit = lambda: None
    _pg2.display = types.ModuleType("pygame.display")
    _pg2.display.set_mode = lambda *a, **k: None
    _pg2.display.set_caption = lambda *a, **k: None
    _pg2.font = types.ModuleType("pygame.font")
    _pg2.font.SysFont = lambda *a, **k: None
    sys.modules["pygame"] = _pg2
    sys.modules["pygame.display"] = _pg2.display
    sys.modules["pygame.font"] = _pg2.font


def _run_single(args):
    """Wrapper for multiprocessing: unpack args and call run_headless."""
    num_agvs, num_carts, duration, tick_dt = args
    return run_headless(
        num_agvs=num_agvs,
        num_carts=num_carts,
        sim_duration=duration,
        tick_dt=tick_dt,
        verbose=False,
    )


def main():
    parser = argparse.ArgumentParser(description="AGV simulation parameter sweep")
    parser.add_argument("--duration", type=float, default=7200.0,
                        help="Simulation duration in sim-seconds (default: 7200 = 2 hours)")
    parser.add_argument("--tick-dt", type=float, default=0.1,
                        help="Simulation tick timestep in seconds (default: 0.1)")
    parser.add_argument("--agvs", type=str, default="2,4,6,8,10,12,14",
                        help="Comma-separated list of AGV counts to sweep")
    parser.add_argument("--carts", type=str, default="4,8,12,16,20,24",
                        help="Comma-separated list of cart counts to sweep")
    parser.add_argument("--csv", type=str, default=None,
                        help="Optional CSV output file path")
    parser.add_argument("--parallel", action="store_true",
                        help="Run sweep using multiprocessing")
    parser.add_argument("--workers", type=int, default=None,
                        help="Number of parallel workers (default: cpu_count, capped at 8)")
    args = parser.parse_args()

    agv_counts = [int(x.strip()) for x in args.agvs.split(",")]
    cart_counts = [int(x.strip()) for x in args.carts.split(",")]
    duration = args.duration
    tick_dt = args.tick_dt

    combos = [(a, c, duration, tick_dt) for a in agv_counts for c in cart_counts]
    total = len(combos)

    print(f"Sweep: {len(agv_counts)} AGV counts x {len(cart_counts)} cart counts = {total} runs")
    print(f"Duration: {duration:.0f}s ({duration/3600:.1f} sim-hours), tick_dt: {tick_dt}s")
    if args.parallel:
        n_workers = args.workers or min(multiprocessing.cpu_count(), 8)
        print(f"Mode: parallel ({n_workers} workers)")
    else:
        print("Mode: serial")
    print()

    results = []

    if args.parallel:
        n_workers = args.workers or min(multiprocessing.cpu_count(), 8)
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(processes=n_workers, initializer=_init_worker) as pool:
            for i, result in enumerate(pool.imap_unordered(_run_single, combos), 1):
                results.append(result)
                print(f"  [{i}/{total}] AGVs={result['num_agvs']:>2}  "
                      f"Carts={result['num_carts']:>2}  "
                      f"Orders={result['completed_orders']:>4}  "
                      f"Wall={result['wall_clock_seconds']:.1f}s")
    else:
        for i, combo in enumerate(combos, 1):
            num_agvs, num_carts, dur, tdt = combo
            print(f"  [{i}/{total}] AGVs={num_agvs}, Carts={num_carts} ...", end="", flush=True)
            result = run_headless(
                num_agvs=num_agvs,
                num_carts=num_carts,
                sim_duration=dur,
                tick_dt=tdt,
                verbose=False,
            )
            results.append(result)
            print(f"  Orders={result['completed_orders']:>4}  "
                  f"Wall={result['wall_clock_seconds']:.1f}s")

    # Sort results by AGVs then carts for display
    results.sort(key=lambda r: (r["num_agvs"], r["num_carts"]))

    # Print summary table
    print()
    header = f"{'AGVs':>5}  {'Carts':>5}  {'Orders':>6}  {'Ord/hr':>6}  " \
             f"{'AvgCycle':>9}  {'Util%':>6}  {'Block%':>7}  {'Wall(s)':>8}"
    print(header)
    print("-" * len(header))

    best = None
    for r in results:
        avg_min = r["avg_cycle_time"] / 60.0 if r["avg_cycle_time"] > 0 else 0.0
        print(f"{r['num_agvs']:>5}  {r['num_carts']:>5}  "
              f"{r['completed_orders']:>6}  "
              f"{r['orders_per_hour']:>6.1f}  "
              f"{avg_min:>8.1f}m  "
              f"{r['agv_utilization']*100:>5.1f}%  "
              f"{r['agv_blocked_fraction']*100:>6.1f}%  "
              f"{r['wall_clock_seconds']:>7.1f}")
        if best is None or r["orders_per_hour"] > best["orders_per_hour"]:
            best = r

    if best:
        print(f"\nBest throughput: {best['orders_per_hour']:.1f} orders/hr "
              f"with {best['num_agvs']} AGVs, {best['num_carts']} carts")

    # Write CSV if requested
    if args.csv:
        fieldnames = [
            "num_agvs", "num_carts", "completed_orders", "orders_per_hour",
            "avg_cycle_time", "agv_utilization", "agv_blocked_fraction",
            "sim_duration", "wall_clock_seconds", "total_ticks",
        ]
        with open(args.csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                row = {k: r[k] for k in fieldnames}
                writer.writerow(row)
        print(f"\nCSV written to: {args.csv}")


if __name__ == "__main__":
    main()
