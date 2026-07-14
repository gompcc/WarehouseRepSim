"""Headless (no-GUI) simulation runner.

Drives the shared :class:`Environment` with a fixed timestep, so entity
placement and cart spawning are identical to the GUI and results are
directly comparable. The Dispatcher (policy) is ticked after each
environment (physics) step, then the environment audits consistency.
"""

from __future__ import annotations

import logging
import time as _time

from .enums import AGVState
from .models import Cart, Order, Job, set_order_seed
from .agv import AGV
from .environment import Environment
from .dispatcher import Dispatcher
from .strategies import StrategyConfig

logger = logging.getLogger(__name__)


def _reset_id_counters() -> None:
    """Reset class-level ID counters so each headless run starts fresh."""
    AGV._next_id = 1
    Cart._next_id = 1
    Order._next_id = 1
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
) -> dict:
    """Run the simulation without pygame, using a fixed timestep.

    Entity entry matches the GUI exactly (policy-fair spawn model):
    - Carts spawn AT the Box Depot: the depot's 8 tiles fill at t=0, then
      one cart per 5 sim-seconds into any tile that is free and not
      targeted by an in-flight job, until ``num_carts`` have entered
    - AGVs stream in single-file through AGV_SPAWN_TILE — the next spawns
      only once the previous has driven off the tile

    Returns a dict of performance metrics, including the environment's
    ``stuck_report`` (stuck carts, buffer thrashing, physics violations).
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
    if isinstance(strategies, dict):
        strategies = StrategyConfig(**strategies)
    wall_start = _time.monotonic()

    env = Environment(event_jsonl=event_jsonl)
    env.agv_preload_remaining = num_agvs
    env.preload_remaining = num_carts
    dispatcher = Dispatcher(env.tiles, strategies=strategies)

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

    wall_elapsed = _time.monotonic() - wall_start
    env.events.close()

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

    return {
        "num_agvs": num_agvs,
        "num_carts": num_carts,
        "seed": seed,
        "strategies": dispatcher.strategies.active_names(),
        "completed_orders": completed,
        "orders_per_hour": orders_per_hour,
        "avg_cycle_time": avg_cycle,
        "cycle_times": cycle_times,
        "agv_utilization": agv_utilization,
        "agv_blocked_fraction": agv_blocked_fraction,
        "station_fill": station_fill,
        "stuck_report": stuck_report,
        "sim_duration": env.sim_elapsed,
        "wall_clock_seconds": wall_elapsed,
        "total_ticks": total_ticks,
    }
