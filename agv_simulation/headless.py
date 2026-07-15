"""Headless (no-GUI) simulation runner.

Drives the shared :class:`Environment` with a fixed timestep, so entity
placement and cart spawning are identical to the GUI and results are
directly comparable. The Dispatcher (policy) is ticked after each
environment (physics) step, then the environment audits consistency.
"""

from __future__ import annotations

import logging
import time as _time

from .enums import AGVState, CartState
from .models import Cart, Order, Job, set_order_seed, set_order_book
from .agv import AGV
from .environment import Environment
from .dispatcher import Dispatcher
from .layout import HighwayLayout
from .strategies import StrategyConfig

logger = logging.getLogger(__name__)


def _reset_id_counters() -> None:
    """Reset class-level ID counters so each headless run starts fresh."""
    AGV._next_id = 1
    Cart._next_id = 1
    Order._next_id = 1
    Order.sizes = []
    Job._next_id = 1


def run_headless(
    num_agvs: int = 10,
    num_carts: int = 25,
    sim_duration: float = 28800.0,
    tick_dt: float = 0.1,
    log_level: str = "INFO",
    log_file: str | None = None,
    event_jsonl: str | None = None,
    seed: int | None = None,
    strategies: StrategyConfig | dict | None = None,
    export: bool = True,
    slotting: str = "sequential",
    picker_strategy: str = "static",
    order_book: bool = True,
    snapshot_interval: float = 60.0,
    results_json: str | None = None,
    highway: tuple[int, int] | None = None,
    picker_management: bool = False,
) -> dict:
    """Run the simulation without pygame, using a fixed timestep.

    Entity entry matches the GUI exactly (policy-fair spawn model):
    - Carts spawn AT the Box Depot: the depot's 8 tiles fill at t=0, then
      one cart per 5 sim-seconds into any tile that is free and not
      targeted by an in-flight job, until ``num_carts`` have entered
    - AGVs stream in single-file through AGV_SPAWN_TILE — the next spawns
      only once the previous has driven off the tile

    Returns a dict of performance metrics, including the environment's
    ``stuck_report`` (stuck carts, buffer thrashing, physics violations)
    and ``snapshots`` — a throughput time series sampled every
    ``snapshot_interval`` sim-seconds (~480 rows per 8h run), the headless
    counterpart of the GUI's live orders/hr strip. Pass ``results_json``
    to also dump ``{metadata, summary, stuck_report, snapshots}`` to that
    path (e.g. ``results/runs/<name>.json``) for programmatic comparison.
    """
    # Configure logging
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(message)s",
        handlers=handlers,
        force=True,
    )

    _reset_id_counters()
    set_order_seed(seed)
    # Canonical fixed demand (15h x 3000 lines/hr book) by default — every
    # arm faces the same order flow; seeds select windows into the book.
    if order_book:
        from .orderbook import ensure_order_book
        set_order_book(ensure_order_book())
    else:
        set_order_book(None)
    if isinstance(strategies, dict):
        strategies = StrategyConfig(**strategies)
    wall_start = _time.monotonic()

    # Dynamic highway: install the requested pillar columns, or reset to
    # the default so a moved layout can't leak between runs in one process
    # (sweeps call run_headless repeatedly).
    layout = HighwayLayout(*highway) if highway else HighwayLayout()

    env = Environment(
        event_jsonl=event_jsonl, slotting=slotting,
        picker_strategy=picker_strategy,
        picker_management=picker_management, layout=layout,
    )
    env.agv_preload_remaining = num_agvs
    env.preload_remaining = num_carts
    dispatcher = Dispatcher(env.tiles, strategies=strategies, pickers=env.pickers)

    total_ticks: int = 0

    logger.info("Headless: streaming %d AGVs, spawning %d carts at Box Depot"
                " over %ds sim-time (seed=%s, strategies=%s)",
                num_agvs, num_carts, int(sim_duration), seed,
                dispatcher.strategies.active_names() or "baseline")

    # Utilization tracking (AGVs appear dynamically as they stream in)
    from collections import defaultdict
    idle_ticks: dict[int, int] = defaultdict(int)
    blocked_ticks: dict[int, int] = defaultdict(int)
    total_tracked: dict[int, int] = defaultdict(int)

    snapshots: list[dict] = []
    next_snapshot = snapshot_interval

    while env.sim_elapsed < sim_duration:
        env.reserved_targets = dispatcher.job_targets()
        env.step(tick_dt)
        dispatcher.update(
            env.carts, env.agvs, env.graph, env.tiles, sim_elapsed=env.sim_elapsed,
        )
        env.audit(tick_dt)

        for agv in env.agvs:
            total_tracked[agv.agv_id] += 1
            if agv.state == AGVState.IDLE:
                idle_ticks[agv.agv_id] += 1
            if agv.is_blocked:
                blocked_ticks[agv.agv_id] += 1

        total_ticks += 1

        if snapshot_interval and env.sim_elapsed >= next_snapshot:
            snapshots.append({
                "t": round(env.sim_elapsed, 1),
                "completed": dispatcher.completed_orders,
                "active_agvs": sum(
                    1 for a in env.agvs if a.state != AGVState.IDLE),
                "blocked_agvs": sum(1 for a in env.agvs if a.is_blocked),
                "waiting_carts": sum(
                    1 for c in env.carts
                    if c.state == CartState.WAITING_FOR_STATION),
                "stuck_cum": env.events.counters.get("stuck", 0),
                "fill": {
                    sid: cur for sid, (cur, _cap, _rate)
                    in dispatcher.get_station_fill(env.carts).items()
                },
            })
            next_snapshot += snapshot_interval

    wall_elapsed = _time.monotonic() - wall_start
    env.events.close()
    set_order_book(None)  # don't leak the book into direct Order() callers

    # Export results (same file as GUI); sweeps pass export=False to keep
    # results/sim_results.md from drowning in hundreds of grid-search runs
    if export:
        dispatcher.export_results(env.sim_elapsed, env.agvs, env.carts)

    completed = dispatcher.completed_orders
    hours = env.sim_elapsed / 3600.0
    orders_per_hour = completed / hours if hours > 0 else 0.0

    cycle_times = list(dispatcher.cycle_times)
    avg_cycle = sum(cycle_times) / len(cycle_times) if cycle_times else 0.0

    total_t = sum(total_tracked.values())
    total_idle = sum(idle_ticks.values())
    total_blocked = sum(blocked_ticks.values())
    agv_utilization = 1.0 - (total_idle / total_t) if total_t > 0 else 0.0
    agv_blocked_fraction = total_blocked / total_t if total_t > 0 else 0.0

    station_fill: dict = {}
    fill_data = dispatcher.get_station_fill(env.carts)
    for sid, (cur, cap, rate) in fill_data.items():
        station_fill[sid] = {"current": cur, "capacity": cap, "fill_rate": rate}

    stuck_report = env.stuck_report()

    logger.info("Headless complete: %d orders in %.0fs sim (%.1fs wall)",
                completed, env.sim_elapsed, wall_elapsed)
    logger.info("Audit: %d stuck events, %d teleports, top thrashers: %s",
                stuck_report["stuck_events"], stuck_report["teleport_events"],
                stuck_report["times_buffered"][:5])

    result = {
        "num_agvs": num_agvs,
        "num_carts": num_carts,
        "seed": seed,
        "strategies": dispatcher.strategies.active_names(),
        "slotting": slotting,
        "picker_strategy": picker_strategy,
        "highway": (layout.left_col, layout.right_col),
        "order_book": order_book,
        "completed_orders": completed,
        "orders_per_hour": orders_per_hour,
        "avg_cycle_time": avg_cycle,
        "cycle_times": cycle_times,
        "order_completion_times": list(dispatcher.order_completion_times),
        "agv_utilization": agv_utilization,
        "agv_blocked_fraction": agv_blocked_fraction,
        "station_fill": station_fill,
        "picker_stats": env.pickers.stats(),
        "stuck_report": stuck_report,
        "snapshots": snapshots,
        "sim_duration": env.sim_elapsed,
        "wall_clock_seconds": wall_elapsed,
        "total_ticks": total_ticks,
    }

    if results_json:
        import json
        import os
        os.makedirs(os.path.dirname(results_json) or ".", exist_ok=True)
        metadata_keys = ("num_agvs", "num_carts", "seed", "strategies",
                        "slotting", "picker_strategy", "sim_duration",
                        "total_ticks", "wall_clock_seconds")
        payload = {
            "metadata": {k: result[k] for k in metadata_keys},
            "summary": {
                k: v for k, v in result.items()
                if k not in metadata_keys
                and k not in ("stuck_report", "snapshots")
            },
            "stuck_report": stuck_report,
            "snapshots": snapshots,
        }
        with open(results_json, "w") as f:
            json.dump(payload, f, indent=1)
        logger.info("Per-run JSON written to %s", results_json)

    return result
