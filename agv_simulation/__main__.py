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
    FPS, SPEED_STEPS,
    AGV_SPAWN_TILE, BOX_DEPOT_TIME,
    PRELOAD_CART_COUNT, PRELOAD_AGV_COUNT,
    OPTIMAL_FLEET,
)
from .agv import AGV
from .aisles import SLOTTING_STRATEGIES
from .layout import OPTIMAL_HIGHWAY, HighwayLayout, get_layout, set_layout
from .map_builder import verify_graph
from .environment import Environment
from .dispatcher import Dispatcher
from .headless import _reset_id_counters
from .models import set_order_seed, set_order_book
from .orderbook import ensure_order_book
from .renderer import panel_max_scroll, render
from .strategies import STRATEGY_INFO

logger = logging.getLogger(__name__)

# Fixed order-stream seed so GUI sessions are comparable with headless A/B
# runs (same demand every session; toggle strategies mid-run to compare).
GUI_ORDER_SEED = 42

# Sampling cadence for the per-slotting picks/hr comparison curves (sim-s).
PICKS_SAMPLE_INTERVAL = 60.0


def _build_world(
    slotting: str,
    strategies,
    picker_strategy: str,
    fleet_target: tuple[int, int],
) -> tuple[Environment, Dispatcher]:
    """Fresh deterministic world. Resetting the ID counters and re-seeding
    means order N is byte-identical in every world, so per-slotting runs
    face the same demand (the F1 fairness rule) and their curves compare."""
    _reset_id_counters()
    set_order_seed(GUI_ORDER_SEED)
    # Canonical fixed demand: every world reads the same 15h x 3000
    # lines/hr order book (order N identical across slotting arms).
    set_order_book(ensure_order_book())
    env = Environment(slotting=slotting, picker_strategy=picker_strategy)
    verify_graph(env.graph, env.tiles)
    dispatcher = Dispatcher(env.tiles, strategies=strategies, pickers=env.pickers)
    env.agv_preload_remaining, env.preload_remaining = fleet_target
    return env, dispatcher


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

    # Fair spawn model: depot fills with carts at t=0 (then 1 per 5 sim-s
    # into free un-targeted depot tiles); AGVs stream in single-file
    # through the spawn tile.
    fleet_target: tuple[int, int] = (PRELOAD_AGV_COUNT, PRELOAD_CART_COUNT)
    env, dispatcher = _build_world("sequential", None, "static", fleet_target)
    tiles = env.tiles
    graph = env.graph

    logger.info("Map built: %d tiles", len(tiles))
    logger.info("Window:    %dx%d px", WINDOW_WIDTH, WINDOW_HEIGHT)
    logger.info("Grid:      %dx%d  (%dpx tiles)", GRID_COLS, GRID_ROWS, TILE_SIZE)
    logger.info("Controls: A=spawn AGV, C=spawn Cart, P=pickup cart, R=return, TAB=cycle, Click=send, D=debug")
    logger.info("          Space=pause, T=auto-spawn, Up/Down=speed steps")
    logger.info("          Drag a highway pillar column sideways to move it"
                " (stations, aisles and products follow; world restarts)")
    logger.info("Press Q or close window to quit.")
    logger.info("Order stream seeded (%d) — comparable across sessions", GUI_ORDER_SEED)
    logger.info("Streaming %d AGVs via spawn tile; spawning %d carts at Box Depot",
                PRELOAD_AGV_COUNT, PRELOAD_CART_COUNT)

    agvs = env.agvs
    carts = env.carts
    selected_agv: AGV | None = None
    speed_index: int = SPEED_STEPS.index(100.0)  # 200x opt-in via Up
    time_scale: float = SPEED_STEPS[speed_index]
    paused: bool = False
    toggle_rects: dict = {}
    strategy_events: list[tuple[float, str]] = []  # graph markers
    agv_constraint_s: float = 0.0  # continuous sim-s with AGVs as constraint

    # Per-slotting picks/hr curves: slotting -> [(sim_t, cumulative picks)].
    # Survives world restarts so strategies can be compared on one graph.
    picks_history: dict[str, list[tuple[float, float]]] = {}
    last_sample_t: float = 0.0

    # Dynamic highway drag state: which pillar the mouse is over / dragging.
    # Dragging rebuilds the world per column step (same reset semantics as
    # the slotting toggle — a moved highway invalidates every live path).
    hover_pillar: str | None = None
    drag_pillar: str | None = None
    drag_exported: bool = False
    drag_moved: bool = False
    cursor_resize: bool = False
    can_set_cursor = hasattr(pygame, "SYSTEM_CURSOR_SIZEWE")
    panel_scroll: int = 0  # mouse-wheel scroll of the right-hand panel

    # Throughput-strip continuity across world rebuilds (pillar drags AND
    # slotting toggles): sample times and cumulative pick counts carry
    # these offsets, so the graph's time axis is session-continuous and
    # the curves visibly adjust to each change instead of resetting.
    # restart_marks are (session time, label) per rebuild — the strip greys
    # out curve stretches younger than EQUILIBRIUM_SECONDS after one and
    # tags each stretch's settled-average line with the label (what the
    # most recent major change was).
    picks_t_offset: float = 0.0
    picks_n_offset: float = 0.0
    picks_w_offset: float = 0.0   # cumulative walk-seconds across rebuilds
    restart_marks: list[tuple[float, str]] = [(0.0, "sequential")]
    # Session-continuous (t, cum picks, cum walk-seconds) — feeds the pink
    # rolling mean-walk-time line on the strip's second y-axis.
    walk_history: list[tuple[float, float, float]] = []

    def bank_curve() -> None:
        """Pin the live curve's final point and bank the old world's time
        and picks into the session offsets (call just before a rebuild)."""
        nonlocal picks_t_offset, picks_n_offset, picks_w_offset
        cur = env.catalog.slotting
        if env.sim_elapsed > 0:
            picks_history.setdefault(cur, []).append((
                picks_t_offset + env.sim_elapsed,
                picks_n_offset + float(env.pickers.picks_done),
            ))
            walk_history.append((
                picks_t_offset + env.sim_elapsed,
                picks_n_offset + float(env.pickers.picks_done),
                picks_w_offset + env.pickers.walk_seconds_total,
            ))
        picks_t_offset += env.sim_elapsed
        picks_n_offset += float(env.pickers.picks_done)
        picks_w_offset += env.pickers.walk_seconds_total

    def apply_layout(new_layout: HighwayLayout, label: str | None = None) -> None:
        """Install a highway layout and rebuild the world with curve
        continuity (same slotting, crews and fleet target carry over).
        *label* names the change on the graph's settled-average line."""
        bank_curve()
        set_layout(new_layout)
        restart_world(env.catalog.slotting, keep_events=True)
        restart_marks.append((
            picks_t_offset,
            label or f"hwy L{new_layout.left_col}·R{new_layout.right_col}",
        ))

    def restart_world(new_slotting: str, keep_events: bool = False) -> None:
        """Throw away the live world and rebuild it (same seed + fleet
        target) under the current slotting and highway layout. Hired
        picker crews carry over: each station keeps its headcount, like
        the AGV/cart fleet target does."""
        nonlocal env, dispatcher, tiles, graph, agvs, carts, selected_agv
        nonlocal strategy_events, agv_constraint_s, last_sample_t
        spawn_enabled = env.spawn_enabled
        crew = {sid: len(ps) for sid, ps in env.pickers.pickers.items()}
        management = env.pickers.management
        env, dispatcher = _build_world(
            new_slotting, dispatcher.strategies, env.pickers.strategy,
            fleet_target,
        )
        env.spawn_enabled = spawn_enabled
        env.pickers.management = management
        for sid, n in crew.items():
            if sid in env.pickers.pickers:
                for _ in range(n - len(env.pickers.pickers[sid])):
                    env.pickers.add_picker(sid)
        tiles, graph = env.tiles, env.graph
        agvs, carts = env.agvs, env.carts
        selected_agv = None       # belonged to the old world
        if not keep_events:
            strategy_events = []  # markers use old-run sim times
        agv_constraint_s = 0.0    # constraint clock restarts too
        last_sample_t = 0.0

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
                    env.spawn_enabled = not env.spawn_enabled
                    logger.info("Auto-spawn: %s", "ON" if env.spawn_enabled else "OFF")

                elif event.key == pygame.K_a:
                    if any(a.pos == AGV_SPAWN_TILE for a in agvs):
                        logger.info("Cannot spawn: spawn tile occupied by another AGV!")
                    else:
                        new_agv = AGV(AGV_SPAWN_TILE)
                        agvs.append(new_agv)
                        selected_agv = new_agv
                        logger.info("Spawned AGV %d at %s", new_agv.agv_id, AGV_SPAWN_TILE)

                elif event.key == pygame.K_c:
                    if env.spawn_cart() is None:
                        logger.info("Box Depot full or fully reserved — no cart spawned!")

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
                # Strategy toggle switches (panel)
                clicked_toggle = None
                for attr, rect in toggle_rects.items():
                    if rect.collidepoint(mx, my):
                        clicked_toggle = attr
                        break
                if clicked_toggle == "slotting_cycle":
                    old = env.catalog.slotting
                    idx = SLOTTING_STRATEGIES.index(old) if old in SLOTTING_STRATEGIES else -1
                    new = SLOTTING_STRATEGIES[(idx + 1) % len(SLOTTING_STRATEGIES)]
                    if env.sim_elapsed > 0:
                        # snapshot the finished run, exactly like the quit path
                        dispatcher.export_results(env.sim_elapsed, agvs, carts)
                    # Session-continuous graph (same as pillar drags): bank
                    # the old arm's segment; the new arm's curve starts at
                    # the current session time. Re-running an arm replaces
                    # its previous segment.
                    bank_curve()
                    picks_history[new] = []
                    restart_world(new, keep_events=True)
                    restart_marks.append((picks_t_offset, new))
                    strategy_events.append(
                        (picks_t_offset, f"slotting {new}")
                    )
                    logger.info(
                        "[Slotting] %s -> %s — world restarted (seed %d, fleet %dA/%dC)",
                        old, new, GUI_ORDER_SEED, *fleet_target,
                    )
                    continue
                if clicked_toggle == "extra_slots":
                    lay = get_layout()
                    new_lay = HighwayLayout(
                        lay.left_col, lay.right_col, not lay.extra_slots,
                    )
                    state = "ON" if new_lay.extra_slots else "OFF"
                    if env.sim_elapsed > 0:
                        dispatcher.export_results(env.sim_elapsed, agvs, carts)
                    apply_layout(new_lay, label=f"extra slots {state.lower()}")
                    strategy_events.append(
                        (picks_t_offset, f"Extra slots {state}")
                    )
                    logger.info(
                        "[Layout] Extra pick slots -> %s (every station "
                        "%+d cart slot)", state, 1 if new_lay.extra_slots else -1,
                    )
                    continue
                if clicked_toggle == "highway_optimum":
                    target = HighwayLayout(
                        *OPTIMAL_HIGHWAY, extra_slots=get_layout().extra_slots,
                    )
                    if get_layout() != target:
                        if env.sim_elapsed > 0:
                            dispatcher.export_results(
                                env.sim_elapsed, agvs, carts,
                            )
                        apply_layout(target, label="optimal highway")
                        strategy_events.append((
                            picks_t_offset,
                            f"hwy opt L{target.left_col}·R{target.right_col}",
                        ))
                        logger.info(
                            "[Highway] Jumped to optimum L=%d R=%d",
                            target.left_col, target.right_col,
                        )
                    continue
                if clicked_toggle == "picker_management":
                    pm = dispatcher.pickers
                    pm.management = not pm.management
                    state = "ON" if pm.management else "OFF"
                    strategy_events.append(
                        (picks_t_offset + env.sim_elapsed,
                         f"Picker management {state}")
                    )
                    # Major change: new settled-average segment
                    restart_marks.append((
                        picks_t_offset + env.sim_elapsed,
                        f"picker mgmt {state.lower()}",
                    ))
                    logger.info(
                        "[Strategy] Picker management -> %s (t=%.0fs)",
                        state, env.sim_elapsed,
                    )
                    continue
                if clicked_toggle == "picker_dynamic":
                    pm = dispatcher.pickers
                    pm.strategy = (
                        "dynamic" if pm.strategy == "static" else "static"
                    )
                    state = "ON" if pm.strategy == "dynamic" else "OFF"
                    strategy_events.append(
                        (picks_t_offset + env.sim_elapsed,
                         f"Dynamic pickers {state}")
                    )
                    # Strategy flips are major changes: new average segment
                    restart_marks.append((
                        picks_t_offset + env.sim_elapsed,
                        f"dyn pickers {state.lower()}",
                    ))
                    logger.info("[Strategy] Dynamic pickers -> %s (t=%.0fs)",
                                state, env.sim_elapsed)
                    continue
                if clicked_toggle:
                    now_on = not getattr(dispatcher.strategies, clicked_toggle)
                    setattr(dispatcher.strategies, clicked_toggle, now_on)
                    label = next(
                        i.label for i in STRATEGY_INFO if i.attr == clicked_toggle
                    )
                    state = "ON" if now_on else "OFF"
                    # Each strategy combo has its own optimal fleet — grow or
                    # gracefully shrink the live fleet to match
                    combo = (
                        dispatcher.strategies.eta_reservations,
                        dispatcher.strategies.global_assignment,
                    )
                    t_agvs, t_carts = OPTIMAL_FLEET.get(combo, (10, 25))
                    fleet_target = (t_agvs, t_carts)  # restarts reproduce it
                    env.retarget_fleet(t_agvs, t_carts)
                    strategy_events.append((
                        picks_t_offset + env.sim_elapsed,
                        f"{label} {state} · fleet {t_agvs}A/{t_carts}C",
                    ))
                    # Major change (fleet retargets too): new average segment
                    restart_marks.append((
                        picks_t_offset + env.sim_elapsed,
                        f"{label} {state.lower()}",
                    ))
                    logger.info(
                        "[Strategy] %s -> %s (t=%.0fs) · fleet target %dA/%dC",
                        label, state, env.sim_elapsed, t_agvs, t_carts,
                    )
                    continue
                if mx >= MAP_WIDTH:
                    continue
                # Grab a highway pillar (its column, rows 8-38) to drag it.
                # Everything attached — stations, aisle lengths, product
                # spread — follows live, one world rebuild per column step.
                _gx, _gy = mx // TILE_SIZE, my // TILE_SIZE
                _lay = get_layout()
                if 8 <= _gy <= 38 and _gx in (_lay.left_col, _lay.right_col):
                    drag_pillar = (
                        "left" if _gx == _lay.left_col else "right"
                    )
                    drag_exported = False
                    drag_moved = False
                    logger.info(
                        "[Highway] Grabbed %s pillar (col %d) — drag "
                        "horizontally, release to finish", drag_pillar, _gx,
                    )
                    continue
                # Click an S station (its tiles or racking block) → hire a
                # picker there. Under the dynamic strategy the newcomer
                # roams that station's side like any other picker.
                _tile = tiles.get((mx // TILE_SIZE, my // TILE_SIZE))
                if (
                    _tile is not None
                    and _tile.station_id
                    and _tile.station_id.startswith("S")
                    and _tile.tile_type in (TileType.PICK_STATION, TileType.RACKING)
                ):
                    sid = _tile.station_id
                    new_picker = env.pickers.add_picker(sid)
                    crew_n = len(env.pickers.pickers[sid])
                    strategy_events.append(
                        (picks_t_offset + env.sim_elapsed,
                         f"+picker {sid} ({crew_n})")
                    )
                    logger.info(
                        "[Pickers] Hired picker %d at %s — crew %d (%s strategy)",
                        new_picker.picker_id, sid, crew_n, env.pickers.strategy,
                    )
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

            elif event.type == pygame.MOUSEMOTION:
                mx, my = event.pos
                gx, gy = mx // TILE_SIZE, my // TILE_SIZE
                if drag_pillar is not None:
                    new_layout = get_layout().move_pillar(drag_pillar, gx)
                    if new_layout != get_layout():
                        if env.sim_elapsed > 0 and not drag_exported:
                            # snapshot the run being abandoned, once per drag
                            dispatcher.export_results(
                                env.sim_elapsed, agvs, carts,
                            )
                            drag_exported = True
                        drag_moved = True
                        apply_layout(new_layout)
                        logger.info(
                            "[Highway] Pillars L=%d R=%d — world rebuilt",
                            new_layout.left_col, new_layout.right_col,
                        )
                else:
                    _lay = get_layout()
                    if (
                        mx < MAP_WIDTH and 8 <= gy <= 38
                        and gx in (_lay.left_col, _lay.right_col)
                    ):
                        hover_pillar = (
                            "left" if gx == _lay.left_col else "right"
                        )
                    else:
                        hover_pillar = None

            elif event.type == pygame.MOUSEWHEEL:
                wx, _wy = pygame.mouse.get_pos()
                if wx >= MAP_WIDTH:  # wheel over the panel column scrolls it
                    panel_scroll = max(0, min(
                        panel_scroll - event.y * 24, panel_max_scroll(),
                    ))

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if drag_pillar is not None:
                    _lay = get_layout()
                    if drag_moved:
                        # one marker per completed drag on the picks/hr graph
                        strategy_events.append((
                            picks_t_offset + env.sim_elapsed,
                            f"hwy L{_lay.left_col}·R{_lay.right_col}",
                        ))
                    logger.info(
                        "[Highway] Released %s pillar — L=%d R=%d",
                        drag_pillar, _lay.left_col, _lay.right_col,
                    )
                    drag_pillar = None

        # Resize cursor over/while dragging a pillar (drag affordance)
        if can_set_cursor:
            want_resize = drag_pillar is not None or hover_pillar is not None
            if want_resize != cursor_resize:
                pygame.mouse.set_cursor(
                    pygame.SYSTEM_CURSOR_SIZEWE if want_resize
                    else pygame.SYSTEM_CURSOR_ARROW
                )
                cursor_resize = want_resize

        # Compute sim delta (zero when paused)
        sim_dt = dt * time_scale if not paused else 0.0

        if not paused:
            env.reserved_targets = dispatcher.job_targets()
            env.step(sim_dt)
            dispatcher.update(carts, agvs, graph, tiles, sim_elapsed=env.sim_elapsed)
            env.audit(sim_dt)

            # Auto-scale AGVs (user rule 2026-07-14): whenever AGVs are the
            # binding constraint for >10 continuous sim-seconds, add one.
            (top_name, _top_pct), _scores = dispatcher.get_constraint(carts, agvs)
            if top_name == "AGVs":
                agv_constraint_s += sim_dt
                if agv_constraint_s >= 10.0:
                    agv_constraint_s = 0.0
                    env.agv_preload_remaining += 1
                    fleet_n = len(agvs) + env.agv_preload_remaining
                    strategy_events.append(
                        (picks_t_offset + env.sim_elapsed, f"+AGV ({fleet_n})")
                    )
                    logger.info(
                        "[AutoScale] AGVs constrained 10s → +1 AGV (fleet %d)",
                        fleet_n,
                    )
            else:
                agv_constraint_s = 0.0

            if env.sim_elapsed - last_sample_t >= PICKS_SAMPLE_INTERVAL:
                picks_history.setdefault(env.catalog.slotting, []).append((
                    picks_t_offset + env.sim_elapsed,
                    picks_n_offset + float(env.pickers.picks_done),
                ))
                walk_history.append((
                    picks_t_offset + env.sim_elapsed,
                    picks_n_offset + float(env.pickers.picks_done),
                    picks_w_offset + env.pickers.walk_seconds_total,
                ))
                last_sample_t = env.sim_elapsed

        toggle_rects = render(
            screen, tiles, font_sm, font_md, agvs, selected_agv, time_scale,
            carts, dispatcher=dispatcher, sim_elapsed=env.sim_elapsed,
            paused=paused, auto_spawn=env.spawn_enabled,
            strategy_events=strategy_events,
            pickers=env.pickers,
            picks_history=picks_history,
            hover_pillar=hover_pillar,
            drag_pillar=drag_pillar,
            restart_marks=restart_marks,
            panel_scroll=panel_scroll,
            walk_history=walk_history,
        )
        pygame.display.flip()

    if env.sim_elapsed > 0:
        dispatcher.export_results(env.sim_elapsed, agvs, carts)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
