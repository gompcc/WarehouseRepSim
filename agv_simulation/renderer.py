"""All pygame rendering functions for the warehouse simulation."""

from __future__ import annotations

import bisect
from typing import TYPE_CHECKING

import pygame

from .enums import TileType, AGVState, CartState
from .constants import (
    TILE_SIZE, MAP_WIDTH, MAP_HEIGHT, PANEL_WIDTH,
    THROUGHPUT_STRIP_H, WINDOW_HEIGHT,
    BG_COLOR, OUTLINE_COLOR, LABEL_COLOR, LABEL_BG,
    TILE_COLORS, AGV_COLOR,
    PANEL_BG, PANEL_TEXT, PANEL_HEADER, PANEL_SEPARATOR,
    PANEL_GREEN, PANEL_YELLOW, PANEL_RED,
    NORTH_HWY_ROW, EAST_HWY_ROW,
)
from .models import STATIONS
from .strategies import STRATEGY_INFO

# Rolling window for the live orders/hr graph (sim-seconds)
THROUGHPUT_WINDOW = 900.0

if TYPE_CHECKING:
    from .agv import AGV
    from .dispatcher import Dispatcher
    from .models import Cart


# Station zone identity colors (categorical palette; legend carries identity)
ZONE_COLORS: dict[str, tuple[int, int, int]] = {
    "S1": (42, 120, 214),   # blue
    "S2": (27, 175, 122),   # aqua
    "S3": (237, 161, 0),    # yellow
    "S4": (0, 131, 0),      # green
    "S5": (74, 58, 167),    # violet
    "S6": (227, 73, 72),    # red
    "S7": (232, 123, 164),  # magenta
    "S8": (235, 104, 52),   # orange
    "S9": (14, 124, 134),   # teal
}


def draw_zone_borders(surface: pygame.Surface) -> None:
    """Color each racking run's border by the station owning its slots.

    Per face: the N face (picked from the walkway above) gets the run's top
    edge, the S face the bottom edge — the two faces of one run can belong
    to different stations, and a face split between stations shows one
    colored segment per owner."""
    from .aisles import get_catalog
    try:
        cat = get_catalog()
    except Exception:
        return
    for bank, run_row, face, x0, x1, sid in cat.zone_border_segments():
        color = ZONE_COLORS.get(sid)
        if color is None:
            continue
        y = run_row * TILE_SIZE if face == "N" else (run_row + 1) * TILE_SIZE - 3
        rect = pygame.Rect(
            round(x0 * TILE_SIZE), y, round((x1 - x0) * TILE_SIZE), 3,
        )
        pygame.draw.rect(surface, color, rect)


def draw_tile(surface: pygame.Surface, tile) -> None:
    """Draw one tile at its grid position."""
    px = tile.x * TILE_SIZE
    py = tile.y * TILE_SIZE
    color = TILE_COLORS[tile.tile_type]
    rect = pygame.Rect(px, py, TILE_SIZE, TILE_SIZE)

    if tile.tile_type == TileType.HIGHWAY:
        pygame.draw.rect(surface, BG_COLOR, rect)
        cx = px + TILE_SIZE // 2
        cy = py + TILE_SIZE // 2
        pygame.draw.circle(surface, color, (cx, cy), TILE_SIZE // 2 - 3)
    elif tile.tile_type == TileType.PARKING:
        if tile.station_id in ("Box_Depot", "Pack_off"):
            pygame.draw.rect(surface, TILE_COLORS[TileType.PACKOFF], rect)
        else:
            pygame.draw.rect(surface, color, rect)
        pygame.draw.rect(surface, OUTLINE_COLOR, rect, 1)
    elif tile.tile_type == TileType.PICK_STATION:
        # Station wears its zone color (light tint fill + solid outline) so
        # it visually matches the aisles it serves — no legend needed.
        zone = ZONE_COLORS.get(tile.station_id)
        if zone:
            tint = tuple(int(c + (255 - c) * 0.60) for c in zone)
            pygame.draw.rect(surface, tint, rect)
            pygame.draw.rect(surface, zone, rect, 2)
        else:
            pygame.draw.rect(surface, color, rect)
            pygame.draw.rect(surface, (200, 160, 30), rect, 1)
    elif tile.tile_type == TileType.RACKING:
        # Station racking area wears a light tint of the station's zone
        # color (replaces the old uniform pale yellow)
        zone = ZONE_COLORS.get(tile.station_id)
        if zone:
            tint = tuple(int(c + (255 - c) * 0.72) for c in zone)
            pygame.draw.rect(surface, tint, rect)
        else:
            pygame.draw.rect(surface, color, rect)
    else:
        pygame.draw.rect(surface, color, rect)


def draw_labels(
    surface: pygame.Surface,
    font_sm: pygame.font.Font,
    font_md: pygame.font.Font,
    station_fill: dict | None = None,
    eta_forecast: dict | None = None,
) -> None:
    """Draw station names, section labels, and live capacity indicators.

    When *eta_forecast* is provided (ETA reservations strategy on), each S
    station additionally shows its predicted occupancy ~60s out ("→n.n").
    """

    def _zone_tint(station_id: str) -> tuple[int, int, int] | None:
        zone = ZONE_COLORS.get(station_id)
        if zone is None:
            return None
        return tuple(int(c + (255 - c) * 0.60) for c in zone)

    def label(
        text: str, cx: int, cy: int,
        font: pygame.font.Font | None = None, bg: bool = True,
    ) -> None:
        f = font or font_sm
        txt = f.render(text, True, LABEL_COLOR)
        r = txt.get_rect(center=(cx, cy))
        if bg:
            pad = 3
            bgr = r.inflate(pad * 2, pad * 2)
            # S-station labels wear their zone tint (station == its aisles)
            bg_fill = _zone_tint(text) or LABEL_BG
            outline = ZONE_COLORS.get(text, OUTLINE_COLOR)
            pygame.draw.rect(surface, bg_fill, bgr)
            pygame.draw.rect(surface, outline, bgr, 1)
        surface.blit(txt, r)

    def capacity_label(station_id: str, cx: int, cy: int) -> None:
        if station_fill and station_id in station_fill:
            current, capacity, rate = station_fill[station_id]
        else:
            capacity = STATIONS.get(station_id, 0)
            current, rate = 0, 0.0
        text = f"{current}/{capacity}"
        if rate <= 0.50:
            color = (30, 140, 30)
        elif rate <= 0.75:
            color = (200, 160, 0)
        else:
            color = (200, 40, 40)
        f = font_sm
        txt = f.render(text, True, color)
        r = txt.get_rect(center=(cx, cy))
        pad = 3
        bgr = r.inflate(pad * 2, pad * 2)
        bg_fill = _zone_tint(station_id) or LABEL_BG
        outline = ZONE_COLORS.get(station_id, OUTLINE_COLOR)
        pygame.draw.rect(surface, bg_fill, bgr)
        pygame.draw.rect(surface, outline, bgr, 1)
        surface.blit(txt, r)

        # Live ETA forecast: predicted occupancy ~60s out (ETA strategy on)
        if eta_forecast and station_id in eta_forecast:
            predicted, cap = eta_forecast[station_id]
            prate = predicted / cap if cap else 0.0
            if prate <= 0.50:
                fcolor = (30, 140, 30)
            elif prate <= 0.75:
                fcolor = (200, 160, 0)
            else:
                fcolor = (200, 40, 40)
            ftxt = font_sm.render(f"→{predicted:.1f}", True, fcolor)
            fr = ftxt.get_rect(center=(cx, cy + TILE_SIZE))
            fbg = fr.inflate(6, 4)
            pygame.draw.rect(surface, (240, 244, 255), fbg)
            pygame.draw.rect(surface, OUTLINE_COLOR, fbg, 1)
            surface.blit(ftxt, fr)

    ts = TILE_SIZE

    # Left-side station labels
    label("S1", int(19.5 * ts + ts / 2), 12 * ts + ts // 2, font_md)
    capacity_label("S1", int(19.5 * ts + ts / 2), 13 * ts + ts // 2)
    label("S2", int(27.5 * ts + ts / 2), int(18 * ts + ts / 2), font_md)
    capacity_label("S2", int(27.5 * ts + ts / 2), int(19 * ts + ts / 2))
    label("S3", int(19.5 * ts + ts / 2), int(24 * ts + ts / 2), font_md)
    capacity_label("S3", int(19.5 * ts + ts / 2), int(25 * ts + ts / 2))
    label("S4", int(27.5 * ts + ts / 2), int(30 * ts + ts / 2), font_md)
    capacity_label("S4", int(27.5 * ts + ts / 2), int(31 * ts + ts / 2))

    # Right-side station labels
    label("S5", 56 * ts + ts // 2, 35 * ts + ts // 2, font_md)
    capacity_label("S5", 56 * ts + ts // 2, 36 * ts + ts // 2)
    label("S6", 48 * ts + ts // 2, 29 * ts + ts // 2, font_md)
    capacity_label("S6", 48 * ts + ts // 2, 30 * ts + ts // 2)
    label("S7", 56 * ts + ts // 2, 23 * ts + ts // 2, font_md)
    capacity_label("S7", 56 * ts + ts // 2, 24 * ts + ts // 2)
    label("S8", 48 * ts + ts // 2, 17 * ts + ts // 2, font_md)
    capacity_label("S8", 48 * ts + ts // 2, 18 * ts + ts // 2)
    label("S9", 56 * ts + ts // 2, 11 * ts + ts // 2, font_md)
    capacity_label("S9", 56 * ts + ts // 2, 12 * ts + ts // 2)

    # Box Depot
    label("Box Depot", 33 * ts + ts // 2, int(2.5 * ts), font_md)
    capacity_label("Box_Depot", 33 * ts + ts // 2, int(3.5 * ts))

    # Pack-off
    label("Packoff Conveyor", int(64.5 * ts), int(1.5 * ts), font_md)
    capacity_label("Pack_off", int(64.5 * ts), int(2.5 * ts))

    # Section labels
    label("South Pallets", 19 * ts, 36 * ts, font_sm, bg=False)
    label("North Pallets", 28 * ts, 36 * ts, font_sm, bg=False)
    label("North Highway", 49 * ts, NORTH_HWY_ROW * ts + ts // 2, font_sm, bg=False)
    label("East Highway", 39 * ts, EAST_HWY_ROW * ts + ts // 2, font_sm, bg=False)
    label("AGV Spawn", 19 * ts, 3 * ts, font_sm)


def draw_agv(surface: pygame.Surface, agv: AGV, font: pygame.font.Font) -> None:
    """Draw an AGV: red circle with black outline and white ID, plus green path dots."""
    if agv.path and agv.state != AGVState.IDLE:
        for i in range(agv.path_index + 1, len(agv.path)):
            tx, ty = agv.path[i]
            px = tx * TILE_SIZE + TILE_SIZE // 2
            py = ty * TILE_SIZE + TILE_SIZE // 2
            pygame.draw.circle(surface, (0, 200, 0), (px, py), 3)

    cx, cy = agv.get_render_pos()
    radius = TILE_SIZE // 2 - 2
    pygame.draw.circle(surface, AGV_COLOR, (cx, cy), radius)
    pygame.draw.circle(surface, (0, 0, 0), (cx, cy), radius, 2)

    if agv.is_blocked:
        pygame.draw.circle(surface, (255, 140, 0), (cx, cy), radius + 2, 2)

    id_text = font.render(str(agv.agv_id), True, (255, 255, 255))
    id_rect = id_text.get_rect(center=(cx, cy))
    surface.blit(id_text, id_rect)


def draw_cart(
    surface: pygame.Surface,
    cart: Cart,
    font: pygame.font.Font,
    carried_render_pos: tuple[int, int] | None = None,
) -> None:
    """Draw a cart: colored rounded rect with black outline and C{id} text."""
    if carried_render_pos:
        cx, cy = carried_render_pos
        cy += 6
    else:
        cx = cart.pos[0] * TILE_SIZE + TILE_SIZE // 2
        cy = cart.pos[1] * TILE_SIZE + TILE_SIZE // 2

    w, h = TILE_SIZE - 4, TILE_SIZE * 5 // 8
    color = cart.get_color()
    rect = pygame.Rect(cx - w // 2, cy - h // 2, w, h)
    pygame.draw.rect(surface, color, rect, border_radius=2)
    # A waiting cart shows WHICH station it waits for: border in that
    # station's zone color (a full S1/S3 explains carts idling far away)
    outline = (0, 0, 0)
    if cart.state == CartState.WAITING_FOR_STATION and cart.order is not None:
        ns = cart.order.next_station()
        if ns is not None:
            outline = ZONE_COLORS.get(f"S{ns}", outline)
        else:
            outline = TILE_COLORS[TileType.PACKOFF]  # all picked → Pack-off
    pygame.draw.rect(surface, outline, rect, 2, border_radius=2)

    id_text = font.render(f"C{cart.cart_id}", True, (0, 0, 0))
    id_rect = id_text.get_rect(center=(cx, cy))
    surface.blit(id_text, id_rect)


def draw_ui(
    surface: pygame.Surface,
    font: pygame.font.Font,
    agvs: list[AGV],
    selected_agv: AGV | None,
    time_scale: float = 1.0,
    carts: list[Cart] | None = None,
    dispatcher: Dispatcher | None = None,
) -> None:
    """Draw status text in bottom-left corner."""
    lines: list[str] = []
    cart_count = len(carts) if carts else 0
    disp_info = ""
    if dispatcher:
        disp_info = (
            f"  |  Jobs: {len(dispatcher.pending_jobs)} pending, "
            f"{len(dispatcher.active_jobs)} active  |  "
            f"Orders completed: {dispatcher.completed_orders}"
        )
    lines.append(
        f"AGVs: {len(agvs)}  Carts: {cart_count}  |  Speed: {time_scale}x  |  "
        f"A=spawn  C=cart  P=pickup  R=return  TAB=cycle{disp_info}"
    )
    if selected_agv:
        sid = selected_agv.agv_id
        st = selected_agv.state.value
        pos = selected_agv.pos
        tgt = selected_agv.target
        carrying = (
            f"  carrying=C{selected_agv.carrying_cart.cart_id}"
            if selected_agv.carrying_cart
            else ""
        )
        timer_str = ""
        if selected_agv.state in (AGVState.PICKING_UP, AGVState.DROPPING_OFF):
            timer_str = f"  timer={selected_agv.action_timer:.1f}s"
        if selected_agv.is_blocked:
            timer_str += f"  BLOCKED {selected_agv.blocked_timer:.1f}s"
        job_str = ""
        if selected_agv.current_job:
            job_str = f"  job={selected_agv.current_job.job_type.value}"
        lines.append(
            f"Selected: AGV {sid}  state={st}  pos={pos}  target={tgt}"
            f"{carrying}{timer_str}{job_str}"
        )
        if selected_agv.carrying_cart and selected_agv.carrying_cart.order:
            cart = selected_agv.carrying_cart
            order = cart.order
            ns = order.next_station()
            next_str = f"S{ns}" if ns else "all picked"
            lines.append(
                f"  Cart C{cart.cart_id} Order #{order.order_id}: lines={order.lines}  "
                f"next={next_str}  timer={cart.process_timer:.1f}s"
            )
    else:
        lines.append("No AGV selected")

    y = MAP_HEIGHT - 10 - len(lines) * 18
    for line in lines:
        txt = font.render(line, True, (0, 0, 0))
        bg_rect = txt.get_rect(topleft=(10, y))
        bg_rect.inflate_ip(8, 4)
        pygame.draw.rect(surface, (255, 255, 255, 200), bg_rect)
        pygame.draw.rect(surface, (100, 100, 100), bg_rect, 1)
        surface.blit(txt, (10, y))
        y += 18


def _draw_toggle_switch(
    surface: pygame.Surface, x: int, y: int, on: bool,
) -> pygame.Rect:
    """Draw a small pill toggle switch; return its rect."""
    w, h = 30, 14
    rect = pygame.Rect(x, y, w, h)
    bg = PANEL_GREEN if on else (80, 80, 95)
    pygame.draw.rect(surface, bg, rect, border_radius=h // 2)
    knob_x = x + w - h // 2 - 1 if on else x + h // 2 + 1
    pygame.draw.circle(surface, (245, 245, 250), (knob_x, y + h // 2), h // 2 - 2)
    return rect


def draw_metrics_panel(
    surface: pygame.Surface,
    font_sm: pygame.font.Font,
    font_md: pygame.font.Font,
    agvs: list[AGV],
    carts: list[Cart],
    dispatcher: Dispatcher | None,
    sim_elapsed: float,
    time_scale: float,
    paused: bool,
    auto_spawn: bool,
    selected_agv: AGV | None = None,
) -> dict[str, pygame.Rect]:
    """Draw the 300px metrics panel; return clickable toggle hitboxes."""
    px = MAP_WIDTH
    panel_rect = pygame.Rect(px, 0, PANEL_WIDTH, WINDOW_HEIGHT)
    pygame.draw.rect(surface, PANEL_BG, panel_rect)
    toggle_rects: dict[str, pygame.Rect] = {}

    # Window is 640px tall since the aisle expansion — keep the panel compact
    y = 8
    line_h = 13
    section_gap = 5

    def header(text: str) -> None:
        nonlocal y
        pygame.draw.line(surface, PANEL_SEPARATOR, (px + 10, y), (px + PANEL_WIDTH - 10, y))
        y += 4
        txt = font_md.render(text, True, PANEL_HEADER)
        surface.blit(txt, (px + 10, y))
        y += line_h + 4

    def row(label_text: str, value: str, color: tuple = PANEL_TEXT) -> None:
        nonlocal y
        txt = font_sm.render(f"  {label_text}: {value}", True, color)
        surface.blit(txt, (px + 8, y))
        y += line_h

    def row_raw(text: str, color: tuple = PANEL_TEXT) -> None:
        nonlocal y
        txt = font_sm.render(f"  {text}", True, color)
        surface.blit(txt, (px + 8, y))
        y += line_h

    # 1. SIMULATION
    header("SIMULATION")
    hours = int(sim_elapsed // 3600)
    mins = int((sim_elapsed % 3600) // 60)
    secs = int(sim_elapsed % 60)
    row("Elapsed", f"{hours:02d}:{mins:02d}:{secs:02d}")
    row("Speed", f"{time_scale}x")
    status_color = PANEL_RED if paused else PANEL_GREEN
    status_text = "PAUSED" if paused else "Running"
    row("Status", status_text, status_color)
    as_color = PANEL_GREEN if auto_spawn else PANEL_TEXT
    row("Auto-spawn", "ON" if auto_spawn else "OFF", as_color)
    y += section_gap

    # 2. FLEET STATUS
    header("FLEET STATUS")
    agv_list = agvs or []
    idle_count = sum(1 for a in agv_list if a.state == AGVState.IDLE)
    active_count = len(agv_list) - idle_count
    row("AGVs", f"{active_count} active / {idle_count} idle / {len(agv_list)} total")

    cart_list = carts or []
    spawned = sum(1 for c in cart_list if c.state == CartState.SPAWNED)
    in_transit = sum(
        1 for c in cart_list if c.state in (
            CartState.TO_BOX_DEPOT, CartState.IN_TRANSIT_TO_PICK,
            CartState.IN_TRANSIT_TO_PACKOFF, CartState.IN_TRANSIT,
        )
    )
    processing = sum(
        1 for c in cart_list if c.state in (
            CartState.AT_BOX_DEPOT, CartState.PICKING, CartState.AT_PACKOFF,
        )
    )
    waiting = sum(1 for c in cart_list if c.state == CartState.WAITING_FOR_STATION)
    completed = sum(1 for c in cart_list if c.state == CartState.COMPLETED)
    row("Carts", f"{len(cart_list)} total")
    row_raw(f"Spawned: {spawned}  Transit: {in_transit}")
    row_raw(f"Processing: {processing}  Waiting: {waiting}  Done: {completed}")
    y += section_gap

    # 3. STATION CAPACITY
    header("STATION CAPACITY")
    fill = dispatcher._station_fill_cache if dispatcher else {}
    station_order = [
        "Box_Depot", "S1", "S2", "S3", "S4",
        "S5", "S6", "S7", "S8", "S9", "Pack_off",
    ]
    for sid in station_order:
        cur, cap, rate = fill.get(sid, (0, STATIONS.get(sid, 0), 0.0))
        pct = int(rate * 100)
        if rate <= 0.50:
            dot_color = PANEL_GREEN
        elif rate <= 0.75:
            dot_color = PANEL_YELLOW
        else:
            dot_color = PANEL_RED
        dot_y = y + line_h // 2
        pygame.draw.circle(surface, dot_color, (px + 16, dot_y), 4)
        display_name = sid.replace("_", " ")
        txt = font_sm.render(f"    {display_name}: {cur}/{cap} ({pct}%)", True, PANEL_TEXT)
        surface.blit(txt, (px + 8, y))
        y += line_h
    y += section_gap

    # 4. THROUGHPUT
    header("THROUGHPUT")
    if dispatcher:
        stats = dispatcher.get_throughput_stats(sim_elapsed)
        row("Completed", str(stats["completed"]))
        avg_c = stats["avg_cycle"]
        if avg_c > 0:
            am = int(avg_c // 60)
            asec = int(avg_c % 60)
            row("Avg cycle", f"{am}m {asec}s")
        else:
            row("Avg cycle", "--")
        row("Orders/hr", f"{stats['per_hour']:.1f}")
    y += section_gap

    # 5. STRATEGIES (clickable toggle switches)
    header("STRATEGIES")
    if dispatcher:
        for info in STRATEGY_INFO:
            on = getattr(dispatcher.strategies, info.attr)
            color = PANEL_GREEN if on else PANEL_TEXT
            txt = font_sm.render(f"  {info.label}", True, color)
            surface.blit(txt, (px + 8, y))
            switch_rect = _draw_toggle_switch(
                surface, px + PANEL_WIDTH - 44, y - 1, on,
            )
            # Whole row is clickable, not just the pill
            toggle_rects[info.attr] = pygame.Rect(
                px + 8, y - 2, PANEL_WIDTH - 16, 16,
            )
            y += 17
        # Picker strategy toggle: static station-bound vs dynamic
        # roam-within-side (pickers never cross the highway)
        pm = getattr(dispatcher, "pickers", None)
        if pm is not None:
            on = pm.strategy == "dynamic"
            color = PANEL_GREEN if on else PANEL_TEXT
            txt = font_sm.render("  Dynamic pickers", True, color)
            surface.blit(txt, (px + 8, y))
            _draw_toggle_switch(surface, px + PANEL_WIDTH - 44, y - 1, on)
            toggle_rects["picker_dynamic"] = pygame.Rect(
                px + 8, y - 2, PANEL_WIDTH - 16, 16,
            )
            y += 17
        # Active slotting strategy (fixed per run — set at catalog init)
        from .aisles import get_catalog
        try:
            slotting_name = get_catalog().slotting
        except Exception:
            slotting_name = None
        if slotting_name:
            txt = font_sm.render(f"  Slotting: {slotting_name}", True, PANEL_TEXT)
            surface.blit(txt, (px + 8, y))
            y += line_h
    y += section_gap

    # 6. CONSTRAINT (what's holding back throughput)
    header("CONSTRAINT")
    if dispatcher and agvs and carts:
        (top_name, top_pct), all_scores = dispatcher.get_constraint(carts, agvs)
        color = PANEL_RED if top_pct > 80 else PANEL_YELLOW if top_pct > 50 else PANEL_GREEN
        row_raw(f"{top_name} ({top_pct}%)", color)
        for name, pct in all_scores[:3]:
            bar = "\u2588" * (pct // 10) + "\u2591" * (10 - pct // 10)
            row(name, f"{bar} {pct}%")
    y += section_gap

    # 7. BOTTLENECK ALERTS
    header("ALERTS")
    if dispatcher:
        alerts = dispatcher.get_bottleneck_alerts(carts or [])
        if alerts:
            for alert in alerts[:3]:
                row_raw(f"! {alert}", PANEL_RED)
        else:
            row_raw("No alerts", PANEL_GREEN)
    y += section_gap

    # 8. SELECTED AGV
    header("SELECTED AGV")
    if selected_agv:
        row("ID", str(selected_agv.agv_id))
        row("State", selected_agv.state.value)
        row("Pos", str(selected_agv.pos))
        if selected_agv.carrying_cart:
            row("Carrying", f"C{selected_agv.carrying_cart.cart_id}")
        if selected_agv.current_job:
            row("Job", selected_agv.current_job.job_type.value)
        if selected_agv.is_blocked:
            row("Blocked", f"{selected_agv.blocked_timer:.1f}s", PANEL_RED)
    else:
        row_raw("None (TAB to select)", PANEL_TEXT)
    y += section_gap

    # 9. Controls hint
    controls_y = WINDOW_HEIGHT - 20
    ctrl_txt = font_sm.render(
        "A:AGV C:Cart T:Auto Space:Pause Up/Dn:Speed", True, PANEL_SEPARATOR
    )
    surface.blit(ctrl_txt, (px + 10, controls_y))

    return toggle_rects


def draw_throughput_strip(
    surface: pygame.Surface,
    font_sm: pygame.font.Font,
    dispatcher: Dispatcher | None,
    sim_elapsed: float,
    strategy_events: list[tuple[float, str]] | None = None,
) -> None:
    """Live orders/hr graph in the strip under the map.

    Rolling ``THROUGHPUT_WINDOW`` rate over the whole run so far, with a
    vertical marker each time a strategy toggle is flipped — the visual
    proof of a toggle's throughput impact.
    """
    strip = pygame.Rect(0, MAP_HEIGHT, MAP_WIDTH, THROUGHPUT_STRIP_H)
    pygame.draw.rect(surface, PANEL_BG, strip)
    pygame.draw.line(surface, PANEL_SEPARATOR, (0, MAP_HEIGHT), (MAP_WIDTH, MAP_HEIGHT))

    title = font_sm.render(
        f"THROUGHPUT  (orders/hr, rolling {int(THROUGHPUT_WINDOW / 60)}min)",
        True, PANEL_HEADER,
    )
    surface.blit(title, (10, MAP_HEIGHT + 4))

    if dispatcher is None or sim_elapsed < 120.0:
        txt = font_sm.render("collecting data…", True, PANEL_TEXT)
        surface.blit(txt, (10, MAP_HEIGHT + 34))
        return

    times = dispatcher.order_completion_times  # chronological
    margin_l, margin_r, margin_t, margin_b = 36, 70, 18, 12
    gx = margin_l
    gy = MAP_HEIGHT + margin_t
    gw = MAP_WIDTH - margin_l - margin_r
    gh = THROUGHPUT_STRIP_H - margin_t - margin_b

    n_samples = min(240, max(2, int(sim_elapsed / 30)))
    rates: list[float] = []
    for i in range(n_samples):
        t = sim_elapsed * (i + 1) / n_samples
        lo = bisect.bisect_right(times, t - THROUGHPUT_WINDOW)
        hi = bisect.bisect_right(times, t)
        window = min(t, THROUGHPUT_WINDOW)
        rates.append((hi - lo) / (window / 3600.0) if window > 0 else 0.0)

    max_rate = max(max(rates) * 1.15, 20.0)

    def to_xy(i: int, rate: float) -> tuple[int, int]:
        x = gx + int(gw * (i + 1) / n_samples)
        y_px = gy + gh - int(gh * rate / max_rate)
        return (x, y_px)

    # Axis + gridline
    pygame.draw.line(surface, PANEL_SEPARATOR, (gx, gy), (gx, gy + gh))
    pygame.draw.line(surface, PANEL_SEPARATOR, (gx, gy + gh), (gx + gw, gy + gh))
    top_lbl = font_sm.render(f"{max_rate:.0f}", True, PANEL_TEXT)
    surface.blit(top_lbl, (gx - top_lbl.get_width() - 4, gy - 4))
    zero_lbl = font_sm.render("0", True, PANEL_TEXT)
    surface.blit(zero_lbl, (gx - zero_lbl.get_width() - 4, gy + gh - 6))

    # Strategy toggle markers
    for t_ev, label in (strategy_events or []):
        if t_ev <= 0 or t_ev > sim_elapsed:
            continue
        ex = gx + int(gw * t_ev / sim_elapsed)
        pygame.draw.line(surface, PANEL_YELLOW, (ex, gy), (ex, gy + gh))
        ev_txt = font_sm.render(label, True, PANEL_YELLOW)
        surface.blit(ev_txt, (min(ex + 3, gx + gw - ev_txt.get_width()), gy - 14))

    # Rate curve
    points = [to_xy(i, r) for i, r in enumerate(rates)]
    if len(points) >= 2:
        pygame.draw.lines(surface, PANEL_GREEN, False, points, 2)

    # Current rate, big, at right
    current = rates[-1] if rates else 0.0
    cur_txt = font_sm.render(f"now: {current:.1f}/hr", True, PANEL_GREEN)
    surface.blit(cur_txt, (gx + gw + 6, gy + 2))
    stats = dispatcher.get_throughput_stats(sim_elapsed)
    avg_txt = font_sm.render(f"avg: {stats['per_hour']:.1f}/hr", True, PANEL_TEXT)
    surface.blit(avg_txt, (gx + gw + 6, gy + 18))


def render(
    screen: pygame.Surface,
    tiles: dict,
    font_sm: pygame.font.Font,
    font_md: pygame.font.Font,
    agvs: list[AGV] | None = None,
    selected_agv: AGV | None = None,
    time_scale: float = 1.0,
    carts: list[Cart] | None = None,
    dispatcher: Dispatcher | None = None,
    sim_elapsed: float = 0.0,
    paused: bool = False,
    auto_spawn: bool = False,
    strategy_events: list[tuple[float, str]] | None = None,
    pickers=None,  # PickerManager | None — shadow-mode pickers (PRD §14.9)
) -> dict[str, pygame.Rect]:
    """Full frame render; returns clickable strategy-toggle hitboxes."""
    screen.fill(BG_COLOR)

    layer_order = [
        TileType.AISLE_RACK, TileType.RACKING, TileType.AGV_SPAWN,
        TileType.BOX_DEPOT, TileType.PACKOFF, TileType.CART_SPAWN,
        TileType.PARKING, TileType.PICK_STATION, TileType.HIGHWAY,
    ]
    by_type: dict[TileType, list] = {tt: [] for tt in layer_order}
    for tile in tiles.values():
        if tile.tile_type in by_type:
            by_type[tile.tile_type].append(tile)

    for tt in layer_order:
        for tile in by_type[tt]:
            draw_tile(screen, tile)

    # Station zone ownership: colored racking-run borders (stations wear
    # the same color, so no legend)
    draw_zone_borders(screen)

    # Station tile color overlay based on fill rate
    station_fill = dispatcher._station_fill_cache if dispatcher else None
    if station_fill and dispatcher:
        overlay = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        for station_id, (current, capacity, rate) in station_fill.items():
            if not station_id.startswith("S"):
                continue
            if rate <= 0.50:
                ov_color = (30, 200, 30, 40)
            elif rate <= 0.75:
                ov_color = (230, 200, 0, 50)
            else:
                ov_color = (220, 50, 50, 60)
            for pos in dispatcher.get_station_tile_positions(station_id):
                overlay.fill(ov_color)
                screen.blit(overlay, (pos[0] * TILE_SIZE, pos[1] * TILE_SIZE))

    eta_forecast = (
        dispatcher.eta_forecast
        if dispatcher and dispatcher.strategies.eta_reservations
        else None
    )
    draw_labels(
        screen, font_sm, font_md,
        station_fill=station_fill, eta_forecast=eta_forecast,
    )

    if carts:
        for cart in carts:
            if cart.carried_by is None:
                draw_cart(screen, cart, font_sm)

    if agvs:
        for agv in agvs:
            draw_agv(screen, agv, font_md)

    if carts:
        for cart in carts:
            if cart.carried_by is not None:
                render_pos = cart.carried_by.get_render_pos()
                draw_cart(screen, cart, font_sm, carried_render_pos=render_pos)

    if pickers is not None:
        from .picker_view import draw_pickers, draw_picker_info
        draw_pickers(screen, pickers)
        draw_picker_info(screen, pickers, font_sm)

    draw_throughput_strip(
        screen, font_sm, dispatcher, sim_elapsed,
        strategy_events=strategy_events,
    )

    return draw_metrics_panel(
        screen, font_sm, font_md, agvs or [], carts or [],
        dispatcher, sim_elapsed, time_scale, paused, auto_spawn,
        selected_agv=selected_agv,
    )
