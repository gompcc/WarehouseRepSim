"""All pygame rendering functions for the warehouse simulation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from .enums import TileType, AGVState, CartState
from .constants import (
    TILE_SIZE, MAP_WIDTH, MAP_HEIGHT, PANEL_WIDTH,
    BG_COLOR, OUTLINE_COLOR, LABEL_COLOR, LABEL_BG,
    TILE_COLORS, AGV_COLOR,
    PANEL_BG, PANEL_TEXT, PANEL_HEADER, PANEL_SEPARATOR,
    PANEL_GREEN, PANEL_YELLOW, PANEL_RED,
    NORTH_HWY_ROW, EAST_HWY_ROW,
)
from .models import STATIONS

if TYPE_CHECKING:
    from .agv import AGV
    from .dispatcher import Dispatcher
    from .models import Cart


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
        pygame.draw.rect(surface, color, rect)
        pygame.draw.rect(surface, (200, 160, 30), rect, 1)
    else:
        pygame.draw.rect(surface, color, rect)


def draw_labels(
    surface: pygame.Surface,
    font_sm: pygame.font.Font,
    font_md: pygame.font.Font,
    station_fill: dict | None = None,
) -> None:
    """Draw station names, section labels, and live capacity indicators."""

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
            pygame.draw.rect(surface, LABEL_BG, bgr)
            pygame.draw.rect(surface, OUTLINE_COLOR, bgr, 1)
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
        pygame.draw.rect(surface, LABEL_BG, bgr)
        pygame.draw.rect(surface, OUTLINE_COLOR, bgr, 1)
        surface.blit(txt, r)

    ts = TILE_SIZE

    # Left-side station labels
    label("S1", int(5.5 * ts + ts / 2), 12 * ts + ts // 2, font_md)
    capacity_label("S1", int(5.5 * ts + ts / 2), 13 * ts + ts // 2)
    label("S2", int(13.5 * ts + ts / 2), int(18 * ts + ts / 2), font_md)
    capacity_label("S2", int(13.5 * ts + ts / 2), int(19 * ts + ts / 2))
    label("S3", int(5.5 * ts + ts / 2), int(24 * ts + ts / 2), font_md)
    capacity_label("S3", int(5.5 * ts + ts / 2), int(25 * ts + ts / 2))
    label("S4", int(13.5 * ts + ts / 2), int(30 * ts + ts / 2), font_md)
    capacity_label("S4", int(13.5 * ts + ts / 2), int(31 * ts + ts / 2))

    # Right-side station labels
    label("S5", 42 * ts + ts // 2, 35 * ts + ts // 2, font_md)
    capacity_label("S5", 42 * ts + ts // 2, 36 * ts + ts // 2)
    label("S6", 34 * ts + ts // 2, 29 * ts + ts // 2, font_md)
    capacity_label("S6", 34 * ts + ts // 2, 30 * ts + ts // 2)
    label("S7", 42 * ts + ts // 2, 23 * ts + ts // 2, font_md)
    capacity_label("S7", 42 * ts + ts // 2, 24 * ts + ts // 2)
    label("S8", 34 * ts + ts // 2, 17 * ts + ts // 2, font_md)
    capacity_label("S8", 34 * ts + ts // 2, 18 * ts + ts // 2)
    label("S9", 42 * ts + ts // 2, 11 * ts + ts // 2, font_md)
    capacity_label("S9", 42 * ts + ts // 2, 12 * ts + ts // 2)

    # Box Depot
    label("Box Depot", 19 * ts + ts // 2, int(2.5 * ts), font_md)
    capacity_label("Box_Depot", 19 * ts + ts // 2, int(3.5 * ts))

    # Pack-off
    label("Packoff Conveyor", int(50.5 * ts), int(1.5 * ts), font_md)
    capacity_label("Pack_off", int(50.5 * ts), int(2.5 * ts))

    # Section labels
    label("South Pallets", 5 * ts, 36 * ts, font_sm, bg=False)
    label("North Pallets", 14 * ts, 36 * ts, font_sm, bg=False)
    label("North Highway", 35 * ts, NORTH_HWY_ROW * ts + ts // 2, font_sm, bg=False)
    label("East Highway", 25 * ts, EAST_HWY_ROW * ts + ts // 2, font_sm, bg=False)
    label("AGV Spawn", 5 * ts, 3 * ts, font_sm)
    label("Cart Spawn", int(3 * ts), int(9.5 * ts), font_sm)


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

    w, h = 16, 10
    color = cart.get_color()
    rect = pygame.Rect(cx - w // 2, cy - h // 2, w, h)
    pygame.draw.rect(surface, color, rect, border_radius=2)
    pygame.draw.rect(surface, (0, 0, 0), rect, 1, border_radius=2)

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
                f"  Cart C{cart.cart_id} Order #{order.order_id}: picks={order.picks}  "
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
) -> None:
    """Draw the 300px metrics panel on the right side of the window."""
    px = MAP_WIDTH
    panel_rect = pygame.Rect(px, 0, PANEL_WIDTH, MAP_HEIGHT)
    pygame.draw.rect(surface, PANEL_BG, panel_rect)

    y = 10
    line_h = 16
    section_gap = 8

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

    # 5. BOTTLENECK ALERTS
    header("ALERTS")
    if dispatcher:
        alerts = dispatcher.get_bottleneck_alerts(carts or [])
        if alerts:
            for alert in alerts[:5]:
                row_raw(f"! {alert}", PANEL_RED)
        else:
            row_raw("No alerts", PANEL_GREEN)
    y += section_gap

    # 6. SELECTED AGV
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

    # 7. Controls hint
    controls_y = MAP_HEIGHT - 20
    ctrl_txt = font_sm.render(
        "A:AGV C:Cart T:Auto Space:Pause Up/Dn:Speed", True, PANEL_SEPARATOR
    )
    surface.blit(ctrl_txt, (px + 10, controls_y))


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
) -> None:
    """Full frame render: background → tiles → labels → carts → AGVs → panel."""
    screen.fill(BG_COLOR)

    layer_order = [
        TileType.RACKING, TileType.AGV_SPAWN, TileType.BOX_DEPOT,
        TileType.PACKOFF, TileType.CART_SPAWN, TileType.PARKING,
        TileType.PICK_STATION, TileType.HIGHWAY,
    ]
    by_type: dict[TileType, list] = {tt: [] for tt in layer_order}
    for tile in tiles.values():
        if tile.tile_type in by_type:
            by_type[tile.tile_type].append(tile)

    for tt in layer_order:
        for tile in by_type[tt]:
            draw_tile(screen, tile)

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

    draw_labels(screen, font_sm, font_md, station_fill=station_fill)

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

    draw_metrics_panel(
        screen, font_sm, font_md, agvs or [], carts or [],
        dispatcher, sim_elapsed, time_scale, paused, auto_spawn,
        selected_agv=selected_agv,
    )
