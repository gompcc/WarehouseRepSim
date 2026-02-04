"""Interactive pygame entry point.

Run with::

    python -m agv_simulation
"""

from __future__ import annotations

import logging
import sys

import pygame

from .enums import AGVState, CartState, TileType
from .constants import (
    TILE_SIZE, GRID_COLS, GRID_ROWS,
    WINDOW_WIDTH, WINDOW_HEIGHT, MAP_WIDTH,
    FPS, SPEED_STEPS, AUTO_SPAWN_INTERVAL,
    AGV_SPAWN_TILE, CART_SPAWN_TILES, BOX_DEPOT_TIME,
)
from .models import Cart
from .agv import AGV
from .map_builder import build_map, build_graph, verify_graph
from .dispatcher import Dispatcher
from .renderer import render

logger = logging.getLogger(__name__)


def main() -> None:
    """Launch the interactive AGV warehouse simulation."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("AGV Warehouse Simulation")
    clock = pygame.time.Clock()

    font_sm = pygame.font.SysFont("Arial", 11)
    font_md = pygame.font.SysFont("Arial", 14, bold=True)

    tiles = build_map()
    graph = build_graph(tiles)

    logger.info("Map built: %d tiles", len(tiles))
    logger.info("Window:    %dx%d px", WINDOW_WIDTH, WINDOW_HEIGHT)
    logger.info("Grid:      %dx%d  (%dpx tiles)", GRID_COLS, GRID_ROWS, TILE_SIZE)
    logger.info("Controls: A=spawn AGV, C=spawn Cart, P=pickup cart, R=return, TAB=cycle, Click=send, D=debug")
    logger.info("          Space=pause, T=auto-spawn, Up/Down=speed steps")
    logger.info("Press Q or close window to quit.")

    verify_graph(graph, tiles)

    dispatcher = Dispatcher(tiles)

    agvs: list[AGV] = []
    carts: list[Cart] = []
    selected_agv: AGV | None = None
    time_scale: float = 1.0
    speed_index: int = 1
    paused: bool = False
    auto_spawn: bool = False
    auto_spawn_timer: float = 0.0
    sim_elapsed: float = 0.0

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_q, pygame.K_ESCAPE):
                    running = False

                elif event.key == pygame.K_UP:
                    speed_index = min(speed_index + 1, len(SPEED_STEPS) - 1)
                    time_scale = SPEED_STEPS[speed_index]
                    logger.info("Speed: %sx", time_scale)

                elif event.key == pygame.K_DOWN:
                    speed_index = max(speed_index - 1, 0)
                    time_scale = SPEED_STEPS[speed_index]
                    logger.info("Speed: %sx", time_scale)

                elif event.key == pygame.K_SPACE:
                    paused = not paused
                    logger.info("PAUSED" if paused else "RESUMED")

                elif event.key == pygame.K_t:
                    auto_spawn = not auto_spawn
                    auto_spawn_timer = 0.0
                    logger.info("Auto-spawn: %s", "ON" if auto_spawn else "OFF")

                elif event.key == pygame.K_a:
                    if any(a.pos == AGV_SPAWN_TILE for a in agvs):
                        logger.info("Cannot spawn: spawn tile occupied by another AGV!")
                    else:
                        new_agv = AGV(AGV_SPAWN_TILE)
                        agvs.append(new_agv)
                        selected_agv = new_agv
                        logger.info("Spawned AGV %d at %s", new_agv.agv_id, AGV_SPAWN_TILE)

                elif event.key == pygame.K_c:
                    occupied = {c.pos for c in carts if c.carried_by is None}
                    spawned = False
                    for spawn_pos in CART_SPAWN_TILES:
                        if spawn_pos not in occupied:
                            new_cart = Cart(spawn_pos)
                            carts.append(new_cart)
                            logger.info("Spawned Cart C%d at %s", new_cart.cart_id, spawn_pos)
                            spawned = True
                            break
                    if not spawned:
                        logger.info("All cart spawn tiles occupied!")

                elif event.key == pygame.K_p:
                    if selected_agv and selected_agv.current_job:
                        logger.info("AGV %d busy with autonomous job", selected_agv.agv_id)
                    elif (
                        selected_agv
                        and selected_agv.state == AGVState.IDLE
                        and not selected_agv.carrying_cart
                    ):
                        best_cart = None
                        best_dist = float("inf")
                        ax, ay = selected_agv.pos
                        for cart in carts:
                            if cart.state in (CartState.SPAWNED, CartState.IDLE) and cart.carried_by is None:
                                dist = abs(cart.pos[0] - ax) + abs(cart.pos[1] - ay)
                                if dist < best_dist:
                                    best_dist = dist
                                    best_cart = cart
                        if best_cart:
                            if selected_agv.pickup_cart(best_cart, graph, tiles):
                                logger.info(
                                    "AGV %d → pickup C%d at %s (%d tiles)",
                                    selected_agv.agv_id, best_cart.cart_id,
                                    best_cart.pos, len(selected_agv.path),
                                )
                            else:
                                logger.info(
                                    "AGV %d: no path to C%d!",
                                    selected_agv.agv_id, best_cart.cart_id,
                                )
                        else:
                            logger.info("No available carts to pick up")
                    elif selected_agv and selected_agv.carrying_cart:
                        logger.info(
                            "AGV %d already carrying C%d",
                            selected_agv.agv_id,
                            selected_agv.carrying_cart.cart_id,
                        )

                elif event.key == pygame.K_r:
                    if selected_agv and selected_agv.state == AGVState.IDLE:
                        if selected_agv.carrying_cart:
                            logger.info("AGV %d carrying cart — drop off first!", selected_agv.agv_id)
                        elif selected_agv.pos == AGV_SPAWN_TILE:
                            logger.info("AGV %d already at spawn", selected_agv.agv_id)
                        elif selected_agv.return_to_spawn(graph, tiles):
                            logger.info(
                                "AGV %d returning to spawn (%d tiles)",
                                selected_agv.agv_id, len(selected_agv.path),
                            )
                        else:
                            logger.info("AGV %d: no path to spawn!", selected_agv.agv_id)

                elif event.key == pygame.K_TAB:
                    if agvs:
                        if selected_agv is None:
                            selected_agv = agvs[0]
                        else:
                            idx = agvs.index(selected_agv)
                            selected_agv = agvs[(idx + 1) % len(agvs)]
                        logger.info("Selected AGV %d", selected_agv.agv_id)

                elif event.key == pygame.K_d:
                    logger.info("\n" + "=" * 60)
                    logger.info("DEBUG DUMP")
                    logger.info("=" * 60)
                    logger.info("\n--- AGV Status ---")
                    if not agvs:
                        logger.info("  (no AGVs spawned)")
                    for agv in agvs:
                        sel = " [SELECTED]" if agv is selected_agv else ""
                        logger.info("  AGV %d%s:", agv.agv_id, sel)
                        logger.info("    state:       %s", agv.state.value)
                        logger.info("    pos:         %s", agv.pos)
                        logger.info(
                            "    path:        %d tiles%s",
                            len(agv.path),
                            " → " + str(agv.path[-1]) if agv.path else "",
                        )
                        logger.info(
                            "    path_index:  %d  progress: %.2f",
                            agv.path_index, agv.path_progress,
                        )
                        logger.info(
                            "    current_job: %s  carrying: %s",
                            agv.current_job.job_id if agv.current_job else None,
                            "C" + str(agv.carrying_cart.cart_id) if agv.carrying_cart else None,
                        )

                    logger.info("\n--- Cart Status ---")
                    if not carts:
                        logger.info("  (no carts spawned)")
                    for cart in carts:
                        at_depot = any(
                            t.station_id == "Box_Depot"
                            for t in [tiles.get(cart.pos)]
                            if t and t.station_id
                        )
                        logger.info("  Cart C%d:", cart.cart_id)
                        logger.info("    state:         %s", cart.state.value)
                        logger.info("    pos:           %s  at_box_depot: %s", cart.pos, at_depot)
                        logger.info(
                            "    process_timer: %.1f  (BOX_DEPOT_TIME=%s)",
                            cart.process_timer, BOX_DEPOT_TIME,
                        )
                        logger.info(
                            "    carried_by:    %s",
                            "AGV " + str(cart.carried_by.agv_id) if cart.carried_by else None,
                        )
                        logger.info(
                            "    order:         %s",
                            cart.order.order_id if cart.order else None,
                        )
                        if cart.order:
                            remaining = [
                                s for s in cart.order.stations_to_visit
                                if s not in cart.order.completed_stations
                            ]
                            logger.info("    remaining:     %s", ["S" + str(s) for s in remaining])
                            reserved = dispatcher._reserved_tiles(carts)
                            for sid_num in remaining:
                                sid = f"S{sid_num}"
                                key = (sid, TileType.PICK_STATION)
                                all_tiles = dispatcher._station_tiles.get(key, [])
                                occupied_count = sum(1 for p in all_tiles if p in reserved)
                                cap = len(all_tiles)
                                logger.info("      %s: %d/%d occupied", sid, occupied_count, cap)

                    logger.info("\n--- Dispatcher ---")
                    logger.info("  pending_jobs:  %d", len(dispatcher.pending_jobs))
                    for j in dispatcher.pending_jobs:
                        logger.info(
                            "    Job #%d %s C%d → %s",
                            j.job_id, j.job_type.value, j.cart.cart_id, j.target_pos,
                        )
                    logger.info("  active_jobs:   %d", len(dispatcher.active_jobs))
                    for j in dispatcher.active_jobs:
                        agv_id = j.assigned_agv.agv_id if j.assigned_agv else "?"
                        logger.info(
                            "    Job #%d %s C%d → %s (AGV %s)",
                            j.job_id, j.job_type.value, j.cart.cart_id,
                            j.target_pos, agv_id,
                        )
                    logger.info("  completed_orders: %d", dispatcher.completed_orders)
                    logger.info("=" * 60 + "\n")

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if mx >= MAP_WIDTH:
                    continue
                if selected_agv and selected_agv.current_job:
                    logger.info("AGV %d busy with autonomous job", selected_agv.agv_id)
                elif selected_agv and selected_agv.state == AGVState.IDLE:
                    gx = mx // TILE_SIZE
                    gy = my // TILE_SIZE
                    clicked = (gx, gy)
                    if clicked in tiles:
                        tile = tiles[clicked]
                        if tile.tile_type in (TileType.PICK_STATION, TileType.PARKING):
                            if selected_agv.carrying_cart:
                                if selected_agv.start_dropoff(clicked, graph, tiles):
                                    logger.info(
                                        "AGV %d → dropoff C%d at %s (%d tiles)",
                                        selected_agv.agv_id,
                                        selected_agv.carrying_cart.cart_id,
                                        clicked, len(selected_agv.path),
                                    )
                                else:
                                    logger.info(
                                        "AGV %d: no path to %s!",
                                        selected_agv.agv_id, clicked,
                                    )
                            else:
                                if selected_agv.set_destination(clicked, graph, tiles):
                                    logger.info(
                                        "AGV %d → %s (%s%s, %d tiles)",
                                        selected_agv.agv_id, clicked,
                                        tile.tile_type.value,
                                        " " + tile.station_id if tile.station_id else "",
                                        len(selected_agv.path),
                                    )
                                else:
                                    logger.info(
                                        "AGV %d: no path to %s!",
                                        selected_agv.agv_id, clicked,
                                    )

        # Compute sim delta (zero when paused)
        sim_dt = dt * time_scale if not paused else 0.0
        sim_elapsed += sim_dt

        # Auto-spawn carts
        if auto_spawn and not paused:
            auto_spawn_timer += sim_dt
            if auto_spawn_timer >= AUTO_SPAWN_INTERVAL:
                auto_spawn_timer -= AUTO_SPAWN_INTERVAL
                occupied = {c.pos for c in carts if c.carried_by is None}
                for spawn_pos in CART_SPAWN_TILES:
                    if spawn_pos not in occupied:
                        new_cart = Cart(spawn_pos)
                        carts.append(new_cart)
                        logger.info("[Auto] Spawned Cart C%d at %s", new_cart.cart_id, spawn_pos)
                        break

        if not paused:
            for agv in agvs:
                agv.update(sim_dt, agvs, carts, graph, tiles)
            for cart in carts:
                cart.update(sim_dt)
            dispatcher.update(carts, agvs, graph, tiles, sim_elapsed=sim_elapsed)

        render(
            screen, tiles, font_sm, font_md, agvs, selected_agv, time_scale,
            carts, dispatcher=dispatcher, sim_elapsed=sim_elapsed,
            paused=paused, auto_spawn=auto_spawn,
        )
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
