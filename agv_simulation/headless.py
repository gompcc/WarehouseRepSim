"""Headless (no-GUI) simulation runner."""

from __future__ import annotations

import contextlib
import logging
import os
import random
import time as _time

from .enums import AGVState, TileType
from .models import Cart, Order, Job
from .agv import AGV
from .map_builder import build_map, build_graph
from .dispatcher import Dispatcher

logger = logging.getLogger(__name__)


def _reset_id_counters() -> None:
    """Reset class-level ID counters so each headless run starts fresh."""
    AGV._next_id = 1
    Cart._next_id = 1
    Order._next_id = 1
    Job._next_id = 1


def run_headless(
    num_agvs: int = 4,
    num_carts: int = 8,
    sim_duration: float = 28800.0,
    tick_dt: float = 0.1,
    verbose: bool = False,
) -> dict:
    """Run the simulation without pygame rendering, using a fixed timestep.

    Returns a dict of performance metrics.
    """
    _reset_id_counters()
    wall_start = _time.monotonic()

    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)

    sim_elapsed: float = 0.0
    total_ticks: int = 0

    # Instant pre-placement of all AGVs and carts on valid tiles
    placeable = [
        pos for pos in graph
        if tiles[pos].tile_type in (TileType.PARKING, TileType.PICK_STATION)
    ]
    random.shuffle(placeable)

    total_entities = num_agvs + num_carts
    if total_entities > len(placeable):
        raise ValueError(
            f"Cannot place {total_entities} entities ({num_agvs} AGVs + "
            f"{num_carts} carts) — only {len(placeable)} PARKING/PICK_STATION "
            f"tiles available in the graph."
        )

    agvs: list[AGV] = []
    carts: list[Cart] = []
    slot = 0
    for _ in range(num_agvs):
        agvs.append(AGV(placeable[slot]))
        slot += 1
    for _ in range(num_carts):
        carts.append(Cart(placeable[slot]))
        slot += 1

    # Utilization tracking
    idle_ticks: dict[int, int] = {agv.agv_id: 0 for agv in agvs}
    blocked_ticks: dict[int, int] = {agv.agv_id: 0 for agv in agvs}
    total_tracked: dict[int, int] = {agv.agv_id: 0 for agv in agvs}

    devnull = open(os.devnull, "w") if not verbose else None
    ctx = contextlib.redirect_stdout(devnull) if devnull else contextlib.nullcontext()

    try:
        with ctx:
            while sim_elapsed < sim_duration:
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
    finally:
        if devnull is not None:
            devnull.close()

    wall_elapsed = _time.monotonic() - wall_start

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
