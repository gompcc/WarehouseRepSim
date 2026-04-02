"""Headless (no-GUI) simulation runner.

Uses identical entity placement and cart spawning as the GUI mode
so that results are directly comparable.
"""

from __future__ import annotations

import logging
import time as _time

from .enums import AGVState, TileType
from .models import Cart, Order, Job
from .agv import AGV
from .map_builder import build_map, build_graph
from .dispatcher import Dispatcher
from .constants import CART_SPAWN_TILES, PRELOAD_SPAWN_INTERVAL, AGV_PARKING_SPOTS

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
) -> dict:
    """Run the simulation without pygame, using a fixed timestep.

    Entity placement matches the GUI exactly:
    - AGVs placed at fixed parking spots near stations
    - Carts spawned one at a time at cart spawn tile, every 5 sim-seconds
    - Spawning stops after ``num_carts`` carts (no continuous spawning)

    Returns a dict of performance metrics.
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
    wall_start = _time.monotonic()

    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)

    sim_elapsed: float = 0.0
    total_ticks: int = 0

    # Place AGVs at fixed spots (matching GUI)
    agvs: list[AGV] = []
    extra_parking = [
        pos for pos in graph
        if tiles[pos].tile_type in (TileType.PARKING, TileType.AGV_SPAWN)
        and tiles[pos].station_id is None
        and pos not in set(AGV_PARKING_SPOTS)
    ]
    for i in range(num_agvs):
        if i < len(AGV_PARKING_SPOTS):
            agvs.append(AGV(AGV_PARKING_SPOTS[i]))
        elif extra_parking:
            agvs.append(AGV(extra_parking.pop(0)))
        else:
            logger.warning("No parking spot for AGV %d", i + 1)

    # Carts spawn one at a time during the sim loop (matching GUI)
    carts: list[Cart] = []
    carts_remaining = num_carts
    spawn_timer: float = 0.0

    logger.info("Headless: %d AGVs, spawning %d carts over %ds sim-time",
                num_agvs, num_carts, int(sim_duration))

    # Utilization tracking
    idle_ticks: dict[int, int] = {agv.agv_id: 0 for agv in agvs}
    blocked_ticks: dict[int, int] = {agv.agv_id: 0 for agv in agvs}
    total_tracked: dict[int, int] = {agv.agv_id: 0 for agv in agvs}

    while sim_elapsed < sim_duration:
        # Cart auto-spawn (matches GUI exactly, stops at num_carts)
        if carts_remaining > 0:
            spawn_timer += tick_dt
            if spawn_timer >= PRELOAD_SPAWN_INTERVAL:
                spawn_timer -= PRELOAD_SPAWN_INTERVAL
                occupied = {c.pos for c in carts if c.carried_by is None}
                for spawn_pos in CART_SPAWN_TILES:
                    if spawn_pos not in occupied:
                        new_cart = Cart(spawn_pos)
                        carts.append(new_cart)
                        carts_remaining -= 1
                        logger.info("[Auto] Spawned Cart C%d at %s (%d remaining)",
                                    new_cart.cart_id, spawn_pos, carts_remaining)
                        break

        for agv in agvs:
            agv.update(tick_dt, agvs, carts, graph, tiles)

        for cart in carts:
            cart.update(tick_dt)

        dispatcher.update(carts, agvs, graph, tiles, sim_elapsed=sim_elapsed)

        for agv in agvs:
            total_tracked[agv.agv_id] += 1
            if agv.state == AGVState.IDLE:
                idle_ticks[agv.agv_id] += 1
            if agv.is_blocked:
                blocked_ticks[agv.agv_id] += 1

        sim_elapsed += tick_dt
        total_ticks += 1

    wall_elapsed = _time.monotonic() - wall_start

    # Export results (same file as GUI)
    dispatcher.export_results(sim_elapsed, agvs, carts)

    completed = dispatcher.completed_orders
    hours = sim_elapsed / 3600.0
    orders_per_hour = completed / hours if hours > 0 else 0.0

    cycle_times = list(dispatcher.cycle_times)
    avg_cycle = sum(cycle_times) / len(cycle_times) if cycle_times else 0.0

    total_t = sum(total_tracked.values())
    total_idle = sum(idle_ticks.values())
    total_blocked = sum(blocked_ticks.values())
    agv_utilization = 1.0 - (total_idle / total_t) if total_t > 0 else 0.0
    agv_blocked_fraction = total_blocked / total_t if total_t > 0 else 0.0

    station_fill: dict = {}
    fill_data = dispatcher.get_station_fill(carts)
    for sid, (cur, cap, rate) in fill_data.items():
        station_fill[sid] = {"current": cur, "capacity": cap, "fill_rate": rate}

    logger.info("Headless complete: %d orders in %.0fs sim (%.1fs wall)",
                completed, sim_elapsed, wall_elapsed)

    return {
        "num_agvs": num_agvs,
        "num_carts": num_carts,
        "completed_orders": completed,
        "orders_per_hour": orders_per_hour,
        "avg_cycle_time": avg_cycle,
        "cycle_times": cycle_times,
        "agv_utilization": agv_utilization,
        "agv_blocked_fraction": agv_blocked_fraction,
        "station_fill": station_fill,
        "sim_duration": sim_elapsed,
        "wall_clock_seconds": wall_elapsed,
        "total_ticks": total_ticks,
    }
