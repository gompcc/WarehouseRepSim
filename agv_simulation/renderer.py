"""All pygame rendering functions for the warehouse simulation."""

from __future__ import annotations

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
    NORTH_HWY_ROW, EAST_HWY_ROW, NUM_SKUS,
)
from .metrics import rolling_rate, ROLLING_WINDOW
from .models import STATIONS
from .strategies import STRATEGY_INFO

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

# One fixed curve/label color per slotting strategy (comparison graph)
SLOTTING_COLORS: dict[str, tuple[int, int, int]] = {
    "sequential": PANEL_GREEN,
    "aisle_proximal": (95, 175, 240),   # blue
    "fibonacci": (235, 150, 60),        # orange
}


def _dim(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """Dimmed variant for finished runs' curves."""
    return tuple(int(v * 0.55) for v in color)


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


# SKU-number overlay: (catalog id, pre-rendered surface). Placement is
# static per run, so the ~2000 tiny labels render once per world build.
_sku_overlay: tuple[int, pygame.Surface] | None = None

SKU_NUMBER_COLOR = (150, 150, 158)  # light grey


def draw_sku_numbers(surface: pygame.Surface) -> None:
    """Light-grey SKU ids at their rack slots so any slotting strategy can
    be visually verified (SKU id = popularity rank; 1 is hottest).

    Only SKU 1 and every 10th SKU are labelled — a full 2000-label overlay
    is unreadable at this tile size; a sparse sample still shows where each
    popularity band lives. N-face labels sit in the tile's top half,
    S-face in the bottom half. The overlay is cached per catalog BUILD
    (``catalog_id``, not ``id()`` — freed addresses get reused, which left
    stale numbers on screen after a pillar drag or slotting toggle)."""
    global _sku_overlay
    from .aisles import get_catalog
    try:
        cat = get_catalog()
    except Exception:
        return
    if _sku_overlay is None or _sku_overlay[0] != cat.catalog_id:
        font_xs = pygame.font.SysFont("Arial", 9)
        overlay = pygame.Surface((MAP_WIDTH, MAP_HEIGHT), pygame.SRCALPHA)
        for sku, slot in cat.slots.items():
            if sku != 1 and sku % 10:
                continue
            txt = font_xs.render(str(sku), True, SKU_NUMBER_COLOR)
            x = int(round(slot.x)) * TILE_SIZE + (TILE_SIZE - txt.get_width()) // 2
            y = slot.run_row * TILE_SIZE + (
                1 if slot.face == "N" else TILE_SIZE - txt.get_height() + 1
            )
            overlay.blit(txt, (x, y))
        _sku_overlay = (cat.catalog_id, overlay)
    surface.blit(_sku_overlay[1], (0, 0))


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
    picker_counts: dict | None = None,
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
        # Live picker headcount at this station (moves with dynamic roam)
        if picker_counts is not None and station_id in picker_counts:
            text += f" ·{picker_counts[station_id]}p"
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

    # S-station labels ride the highway pillars (dynamic layout): name and
    # capacity centred on the station's racking block, plus the station's
    # popularity-weighted mean pick-cycle time (expected walk for one pick
    # there, weighted by SKU order popularity).
    from .aisles import get_catalog
    from .layout import get_layout
    try:
        avg_walk = get_catalog().station_avg_walk_s()
    except Exception:
        avg_walk = {}
    for s in get_layout().stations:
        cx = int((s.rack_x0 + s.rack_x1) / 2 * ts + ts / 2)
        row = (s.y0 + s.y1) // 2
        label(s.sid, cx, row * ts + ts // 2, font_md)
        capacity_label(s.sid, cx, (row + 1) * ts + ts // 2)
        walk = avg_walk.get(s.sid)
        if walk is not None:
            # Below the capacity line; drop one more row when the ETA
            # forecast (drawn by capacity_label) occupies that spot.
            dy = 2 if (eta_forecast and s.sid in eta_forecast) else 1
            wtxt = font_sm.render(f"μ{walk:.0f}s", True, (90, 60, 160))
            wr = wtxt.get_rect(center=(cx, (row + 1 + dy) * ts + ts // 2))
            wbg = wr.inflate(6, 2)
            pygame.draw.rect(surface, LABEL_BG, wbg)
            pygame.draw.rect(surface, OUTLINE_COLOR, wbg, 1)
            surface.blit(wtxt, wr)

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
    _lay = get_layout()
    label(
        "East Highway",
        (_lay.left_col + _lay.right_col) // 2 * ts,
        EAST_HWY_ROW * ts + ts // 2, font_sm, bg=False,
    )
    label("AGV Spawn", 19 * ts, 3 * ts, font_sm)


def draw_pillar_handles(
    surface: pygame.Surface,
    font: pygame.font.Font,
    hover_pillar: str | None = None,
    drag_pillar: str | None = None,
) -> None:
    """Drag affordance for the two movable highway pillars: a faint band
    over each pillar column (rows 8-38), brighter on hover, brightest while
    dragging — plus a grip marker and a live column readout during a drag.
    Dragging a pillar horizontally moves the stations, aisle boundaries and
    product distribution attached to it (world rebuilds per column step)."""
    from .layout import get_layout
    layout = get_layout()
    top, bottom = 8, EAST_HWY_ROW
    h = (bottom - top + 1) * TILE_SIZE
    for name, col in (("left", layout.left_col), ("right", layout.right_col)):
        if drag_pillar == name:
            alpha = 90
        elif drag_pillar is None and hover_pillar == name:
            alpha = 60
        else:
            alpha = 22
        band = pygame.Surface((TILE_SIZE, h), pygame.SRCALPHA)
        band.fill((30, 90, 220, alpha))
        surface.blit(band, (col * TILE_SIZE, top * TILE_SIZE))
        active = drag_pillar == name or (
            drag_pillar is None and hover_pillar == name
        )
        if not active:
            continue
        cx = col * TILE_SIZE + TILE_SIZE // 2
        cy = ((top + bottom) // 2) * TILE_SIZE + TILE_SIZE // 2
        grip = font.render("<->", True, (25, 60, 160))
        r = grip.get_rect(center=(cx, cy))
        bg = r.inflate(6, 4)
        pygame.draw.rect(surface, LABEL_BG, bg)
        pygame.draw.rect(surface, OUTLINE_COLOR, bg, 1)
        surface.blit(grip, r)
        if drag_pillar == name:
            ctxt = font.render(f"col {col}", True, (25, 60, 160))
            cr = ctxt.get_rect(center=(cx, cy + 18))
            cbg = cr.inflate(6, 4)
            pygame.draw.rect(surface, LABEL_BG, cbg)
            pygame.draw.rect(surface, OUTLINE_COLOR, cbg, 1)
            surface.blit(ctxt, cr)


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
    scroll: int = 0,
) -> dict[str, pygame.Rect]:
    """Draw the 300px metrics panel; return clickable toggle hitboxes.

    *scroll* shifts the content up (mouse wheel over the panel) — hitboxes
    are returned in screen coordinates, so clicks keep working while
    scrolled. The visible region is clipped to the panel column."""
    px = MAP_WIDTH
    panel_rect = pygame.Rect(px, 0, PANEL_WIDTH, WINDOW_HEIGHT)
    pygame.draw.rect(surface, PANEL_BG, panel_rect)
    toggle_rects: dict[str, pygame.Rect] = {}

    surface.set_clip(panel_rect)
    y = 8 - scroll
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

    # Highway pillars + one-click jump to the sweep optimum
    from .layout import OPTIMAL_HIGHWAY, get_layout
    _lay = get_layout()
    at_opt = (_lay.left_col, _lay.right_col) == OPTIMAL_HIGHWAY
    hw_txt = font_sm.render(
        f"  Highway: L{_lay.left_col}·R{_lay.right_col}", True, PANEL_TEXT,
    )
    surface.blit(hw_txt, (px + 8, y))
    if at_opt:
        ok = font_sm.render("✓ optimal", True, PANEL_GREEN)
        surface.blit(ok, (px + 8 + hw_txt.get_width() + 8, y))
    else:
        btxt = font_sm.render(
            f"→ L{OPTIMAL_HIGHWAY[0]}·R{OPTIMAL_HIGHWAY[1]}",
            True, (235, 240, 255),
        )
        btn = pygame.Rect(
            px + 8 + hw_txt.get_width() + 8, y - 1,
            btxt.get_width() + 10, 14,
        )
        pygame.draw.rect(surface, (50, 80, 160), btn, border_radius=4)
        pygame.draw.rect(surface, PANEL_HEADER, btn, 1, border_radius=4)
        surface.blit(btxt, (btn.x + 5, btn.y + 1))
        toggle_rects["highway_optimum"] = btn
    y += line_h
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
        # Picker strategy toggle: static station-bound vs dynamic two-pool
        # labour sharing (outer ring around the track / central island)
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
            # Picker management: auto-staffing controller — sizes every
            # station's crew from live demand (queueing rule, no lookahead)
            on = pm.management
            color = PANEL_GREEN if on else PANEL_TEXT
            txt = font_sm.render("  Picker management", True, color)
            surface.blit(txt, (px + 8, y))
            _draw_toggle_switch(surface, px + PANEL_WIDTH - 44, y - 1, on)
            toggle_rects["picker_management"] = pygame.Rect(
                px + 8, y - 2, PANEL_WIDTH - 16, 16,
            )
            y += 17
        # Slotting strategy: clicking cycles to the next arm and RESTARTS
        # the sim (products move, so the world must rebuild)
        from .aisles import get_catalog
        try:
            slotting_name = get_catalog().slotting
        except Exception:
            slotting_name = None
        if slotting_name:
            color = SLOTTING_COLORS.get(slotting_name, PANEL_TEXT)
            txt = font_sm.render(f"  Slotting: {slotting_name}", True, color)
            surface.blit(txt, (px + 8, y))
            hint = font_sm.render("(click: next+restart)", True, PANEL_SEPARATOR)
            surface.blit(hint, (px + PANEL_WIDTH - hint.get_width() - 8, y))
            toggle_rects["slotting_cycle"] = pygame.Rect(
                px + 8, y - 2, PANEL_WIDTH - 16, 16,
            )
            y += 17
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

    # Content height (pre-scroll) — the main loop clamps the wheel with it
    global _panel_content_h
    _panel_content_h = y + scroll + 24
    surface.set_clip(None)

    # Scrollbar hint when the content overflows the column
    if _panel_content_h > WINDOW_HEIGHT:
        frac = WINDOW_HEIGHT / _panel_content_h
        bar_h = max(24, int(WINDOW_HEIGHT * frac))
        denom = _panel_content_h - WINDOW_HEIGHT
        bar_y = int(scroll / denom * (WINDOW_HEIGHT - bar_h)) if denom else 0
        pygame.draw.rect(
            surface, (70, 70, 90),
            pygame.Rect(px + PANEL_WIDTH - 5, bar_y, 3, bar_h),
        )

    # 9. Controls hint (pinned to the window bottom, not scrolled)
    controls_y = WINDOW_HEIGHT - 20
    ctrl_txt = font_sm.render(
        "A:AGV C:Cart T:Auto Space:Pause Up/Dn:Speed", True, PANEL_SEPARATOR
    )
    surface.blit(ctrl_txt, (px + 10, controls_y))

    return toggle_rects


def panel_max_scroll() -> int:
    """Furthest the panel content can scroll (0 when it all fits)."""
    return max(0, _panel_content_h - WINDOW_HEIGHT)


_panel_content_h: int = 0


def _draw_location_spectrum(
    surface: pygame.Surface, font: pygame.font.Font,
    pickers, rect: pygame.Rect,
) -> None:
    """Pick frequency across the 2000 physical locations (x = geometric
    location index along the aisles, west→east). One thin vertical line
    per pixel column builds up as picks complete: the skyline shows how
    the active slotting spreads picker traffic over the warehouse — flat
    is balanced, spiky means a few hot spots do all the work."""
    from .aisles import get_catalog
    title = font.render("picks by product location 1–2000", True, PANEL_HEADER)
    surface.blit(title, (rect.x, rect.y - 14))
    pygame.draw.line(
        surface, PANEL_SEPARATOR, (rect.x, rect.bottom), (rect.right, rect.bottom),
    )
    sku_picks = getattr(pickers, "sku_picks", None) if pickers else None
    try:
        loc_of = get_catalog().sku_location_index
    except Exception:
        return
    if not sku_picks:
        txt = font.render("collecting…", True, PANEL_TEXT)
        surface.blit(txt, (rect.x + 4, rect.y + rect.h // 2 - 6))
        return
    cols = [0.0] * rect.w
    for sku, n in sku_picks.items():
        idx = loc_of.get(sku)
        if idx is None:
            continue
        cols[min(rect.w - 1, (idx - 1) * rect.w // NUM_SKUS)] += n
    peak = max(cols)
    for i, c in enumerate(cols):
        if not c:
            continue
        h = max(1, round((rect.h - 2) * c / peak))
        pygame.draw.line(
            surface, (95, 175, 240),
            (rect.x + i, rect.bottom - 1), (rect.x + i, rect.bottom - h),
        )
    n_lbl = font.render(f"{sum(sku_picks.values())} picks", True, PANEL_TEXT)
    surface.blit(n_lbl, (rect.right - n_lbl.get_width(), rect.y - 14))
    for v in (0, 500, 1000, 1500, 2000):
        lbl = font.render(str(v), True, (110, 112, 130))
        lx = rect.x + rect.w * v // 2000 - lbl.get_width() // 2
        lx = min(max(lx, rect.x), rect.right - lbl.get_width())
        surface.blit(lbl, (lx, rect.bottom + 2))


def _draw_station_load_bars(
    surface: pygame.Surface, font: pygame.font.Font,
    carts, rect: pygame.Rect,
    picker_counts: dict | None = None,
    constraint: str | None = None,
) -> None:
    """Live station view, one column per S station:

    - BAR: the station's whole order backlog (active orders that still
      need to visit it), zone-colored — RED when the station is the
      dispatcher's current binding constraint.
    - WHITE TICK: cart capacity, on the same left scale as the backlog.
    - GREEN DOT: picker headcount there, on the right-hand axis.
    """
    load = {i: 0 for i in range(1, 10)}
    for cart in carts or []:
        order = getattr(cart, "order", None)
        if order is None:
            continue
        for s in getattr(order, "stations_to_visit", ()):
            if s not in order.completed_stations:
                load[s] += 1
    caps = {i: STATIONS.get(f"S{i}", 0) for i in range(1, 10)}
    pk = picker_counts or {}
    title = font.render("backlog | cap – | pickers ●", True, PANEL_HEADER)
    surface.blit(title, (rect.x, rect.y - 14))
    pygame.draw.line(
        surface, PANEL_SEPARATOR, (rect.x, rect.bottom), (rect.right, rect.bottom),
    )
    left_max = max(max(load.values()), max(caps.values()), 1)
    right_max = max([pk.get(f"S{i}", 0) for i in range(1, 10)] + [2])
    bw = rect.w / 9
    dot_color = (20, 150, 60)
    for i in range(1, 10):
        sid = f"S{i}"
        cx = round(rect.x + (i - 1) * bw)
        zone = ZONE_COLORS.get(sid, PANEL_TEXT)
        color = PANEL_RED if constraint == sid else zone
        c = load[i]
        if c:
            h = max(2, round(rect.h * c / left_max))
            pygame.draw.rect(surface, color, pygame.Rect(
                cx + 2, rect.bottom - h, round(bw) - 4, h,
            ))
            cnt = font.render(str(c), True, PANEL_TEXT)
            surface.blit(cnt, (
                round(cx + (bw - cnt.get_width()) / 2),
                max(rect.y - 2, rect.bottom - h - 12),
            ))
        if caps[i]:
            cap_y = rect.bottom - round(rect.h * caps[i] / left_max)
            pygame.draw.line(
                surface, (235, 238, 245),
                (cx + 1, cap_y), (cx + round(bw) - 3, cap_y),
            )
        n_pick = pk.get(sid, 0)
        if n_pick:
            dot_y = rect.bottom - round(rect.h * n_pick / right_max)
            pygame.draw.circle(
                surface, dot_color,
                (round(cx + bw / 2), max(rect.y + 3, dot_y)), 3,
            )
        lbl = font.render(str(i), True, color)
        surface.blit(
            lbl, (round(cx + (bw - lbl.get_width()) / 2), rect.bottom + 2),
        )
    # Right axis (pickers) scale: max value at the top in dot color
    r_lbl = font.render(str(right_max), True, dot_color)
    surface.blit(r_lbl, (rect.right + 3, rect.y - 4))
    # Left axis (orders/carts) scale
    l_lbl = font.render(str(left_max), True, (110, 112, 130))
    surface.blit(l_lbl, (rect.x - l_lbl.get_width() - 3, rect.y - 4))


def draw_throughput_strip(
    surface: pygame.Surface,
    font_sm: pygame.font.Font,
    dispatcher: Dispatcher | None,
    sim_elapsed: float,
    strategy_events: list[tuple[float, str]] | None = None,
    picks_history: dict[str, list[tuple[float, float]]] | None = None,
    restart_marks: list[tuple[float, str]] | None = None,
    carts=None,
    agvs=None,
    picker_counts: dict | None = None,
    pickers=None,
) -> None:
    """Per-slotting picks/hr graph in the strip under the map.

    One rolling-``ROLLING_WINDOW`` curve per slotting strategy on a shared
    session-continuous time axis (pillar drags and slotting toggles carry
    the timeline forward): finished runs dimmed, the live run bright.
    Yellow markers flag strategy toggles and layout/slotting changes.
    ``restart_marks`` are the session times of world rebuilds — curve
    points younger than ``EQUILIBRIUM_SECONDS`` after a rebuild draw GREY
    (the pipeline is still refilling; don't read the rate yet).
    """
    strip = pygame.Rect(0, MAP_HEIGHT, MAP_WIDTH, THROUGHPUT_STRIP_H)
    pygame.draw.rect(surface, PANEL_BG, strip)
    pygame.draw.line(surface, PANEL_SEPARATOR, (0, MAP_HEIGHT), (MAP_WIDTH, MAP_HEIGHT))

    title = font_sm.render(
        f"LINES/HR by slotting  (rolling {int(ROLLING_WINDOW / 60)}min)",
        True, PANEL_HEADER,
    )
    surface.blit(title, (10, MAP_HEIGHT + 4))

    from .aisles import get_catalog
    try:
        current_name = get_catalog().slotting
    except Exception:
        current_name = None

    # Second band, BELOW the temporal graph: order-size bell + live
    # station loading, full-width side by side.
    band_y = MAP_HEIGHT + 158
    pygame.draw.line(
        surface, PANEL_SEPARATOR, (0, band_y), (MAP_WIDTH, band_y),
    )
    _draw_location_spectrum(
        surface, font_sm, pickers,
        pygame.Rect(36, band_y + 22, 320, 96),
    )
    constraint_name = None
    if dispatcher is not None and carts is not None and agvs is not None:
        try:
            (constraint_name, _pct), _scores = dispatcher.get_constraint(
                carts, agvs,
            )
        except Exception:
            constraint_name = None
    _draw_station_load_bars(
        surface, font_sm, carts, pygame.Rect(450, band_y + 22, 480, 96),
        picker_counts=picker_counts, constraint=constraint_name,
    )

    curves: list[tuple[str, list[tuple[float, float]]]] = []
    for name, series in (picks_history or {}).items():
        pts = rolling_rate(series)
        if len(pts) >= 2:
            curves.append((name, pts))
    # draw the live run last (on top)
    curves.sort(key=lambda c: c[0] == current_name)

    if not curves:
        txt = font_sm.render("collecting data…", True, PANEL_TEXT)
        surface.blit(txt, (10, MAP_HEIGHT + 34))
        return

    gx = 36
    gy = MAP_HEIGHT + 18
    gw = MAP_WIDTH - 36 - 70   # full-width temporal graph (top band)
    gh = 116                   # leaves room for the time axis above band 2

    x_max = max(pts[-1][0] for _, pts in curves)
    max_rate = max(max(r for _, r in pts) for _, pts in curves) * 1.15
    max_rate = max(max_rate, 50.0)

    def to_xy(t: float, rate: float) -> tuple[int, int]:
        x = gx + int(gw * min(t / x_max, 1.0))
        y_px = gy + gh - int(gh * min(rate / max_rate, 1.0))
        return (x, y_px)

    # Axis + labels
    pygame.draw.line(surface, PANEL_SEPARATOR, (gx, gy), (gx, gy + gh))
    pygame.draw.line(surface, PANEL_SEPARATOR, (gx, gy + gh), (gx + gw, gy + gh))
    top_lbl = font_sm.render(f"{max_rate:.0f}", True, PANEL_TEXT)
    surface.blit(top_lbl, (gx - top_lbl.get_width() - 4, gy - 4))
    zero_lbl = font_sm.render("0", True, PANEL_TEXT)
    surface.blit(zero_lbl, (gx - zero_lbl.get_width() - 4, gy + gh - 6))

    # Horizontal gridlines at round lines/hr steps
    grid_step = next(
        (s for s in (10, 20, 50, 100, 200, 250, 500, 1000, 2000)
         if max_rate / s <= 5), 5000,
    )
    v = grid_step
    while v < max_rate:
        yv = gy + gh - int(gh * v / max_rate)
        pygame.draw.line(surface, (50, 50, 66), (gx + 1, yv), (gx + gw, yv))
        g_lbl = font_sm.render(f"{v}", True, (110, 112, 130))
        surface.blit(g_lbl, (gx - g_lbl.get_width() - 4, yv - 6))
        v += grid_step

    # Time axis (session sim-time) along the bottom
    t_step = next(
        (s for s in (600, 900, 1800, 3600, 7200, 14400, 28800)
         if x_max / s <= 8), 57600,
    )
    tt = t_step
    while tt < x_max:
        tx = gx + int(gw * tt / x_max)
        pygame.draw.line(surface, PANEL_SEPARATOR, (tx, gy + gh), (tx, gy + gh + 3))
        t_txt = f"{tt / 3600:g}h" if tt >= 3600 else f"{int(tt / 60)}m"
        t_lbl = font_sm.render(t_txt, True, (110, 112, 130))
        surface.blit(t_lbl, (tx - t_lbl.get_width() // 2, gy + gh + 4))
        tt += t_step

    # Dispatch-toggle markers (current run's sim times)
    for t_ev, label in (strategy_events or []):
        if t_ev <= 0 or t_ev > x_max:
            continue
        ex = gx + int(gw * t_ev / x_max)
        pygame.draw.line(surface, PANEL_YELLOW, (ex, gy), (ex, gy + gh))
        ev_txt = font_sm.render(label, True, PANEL_YELLOW)
        surface.blit(ev_txt, (min(ex + 3, gx + gw - ev_txt.get_width()), gy - 14))

    from .metrics import EQUILIBRIUM_SECONDS

    # Major-change marks: (session time, label). Tolerate bare floats.
    marks: list[tuple[float, str]] = sorted(
        (float(m), "") if isinstance(m, (int, float))
        else (float(m[0]), str(m[1]))
        for m in (restart_marks or [(0.0, "")])
    )
    mark_times = [t for t, _ in marks]

    def _is_stable(t: float) -> bool:
        last = max((m for m in mark_times if m <= t), default=0.0)
        return t - last >= EQUILIBRIUM_SECONDS

    grey = (120, 120, 130)
    current_rate: float | None = None
    live_stable = True
    for name, pts in curves:
        base = SLOTTING_COLORS.get(name, PANEL_TEXT)
        is_live = name == current_name
        color = base if is_live else _dim(base)
        # Pairwise draw so restabilising stretches (young after a world
        # rebuild) render grey while settled stretches keep their color
        for (t1, r1), (t2, r2) in zip(pts, pts[1:]):
            seg_color = color if _is_stable(t2) else grey
            pygame.draw.line(
                surface, seg_color, to_xy(t1, r1), to_xy(t2, r2),
                2 if is_live else 1,
            )
        if is_live:
            current_rate = pts[-1][1]
            live_stable = _is_stable(pts[-1][0])

    # Settled-average per state: for each stretch between world rebuilds
    # (layout / slotting changes), average the lines/hr AFTER its warm-up
    # and draw it as a flat horizontal line across the stretch — the
    # "active average" of that configuration, so changes compare at a
    # glance. Computed from the raw cumulative samples, not the rolling
    # curve, so it is exact.
    merged = sorted(
        pt for series in (picks_history or {}).values() for pt in series
    )
    avg_color = (225, 228, 240)
    active_avg: float | None = None
    for (m0, m_label), m1 in zip(marks, mark_times[1:] + [x_max]):
        settled = [
            (t, c) for t, c in merged
            if m0 + EQUILIBRIUM_SECONDS <= t <= m1
        ]
        if len(settled) < 2 or settled[-1][0] <= settled[0][0]:
            continue
        (t0, c0), (t1, c1) = settled[0], settled[-1]
        seg_avg = (c1 - c0) / (t1 - t0) * 3600.0
        y_avg = gy + gh - int(gh * min(seg_avg / max_rate, 1.0))
        x0 = gx + int(gw * min(m0 / x_max, 1.0))
        x1 = gx + int(gw * min(m1 / x_max, 1.0))
        pygame.draw.line(surface, avg_color, (x0, y_avg), (x1, y_avg), 1)
        a_text = f"ø{seg_avg:.0f} · {m_label}" if m_label else f"ø{seg_avg:.0f}"
        a_lbl = font_sm.render(a_text, True, avg_color)
        surface.blit(
            a_lbl,
            (max(x0 + 2, x1 - a_lbl.get_width() - 2), max(gy, y_avg - 12)),
        )
        if m1 == x_max:
            active_avg = seg_avg

    # Legend (top-right of the plot area), live entry bright
    lx = gx + gw - 4
    for name, _ in reversed(curves):
        base = SLOTTING_COLORS.get(name, PANEL_TEXT)
        col = base if name == current_name else _dim(base)
        lbl = font_sm.render(name, True, col)
        lx -= lbl.get_width()
        surface.blit(lbl, (lx, gy - 14))
        pygame.draw.rect(surface, col, pygame.Rect(lx - 10, gy - 9, 7, 3))
        lx -= 16

    # Current-run readouts at right
    live_color = SLOTTING_COLORS.get(current_name or "", PANEL_TEXT)
    if current_rate is not None:
        now_color = live_color if live_stable else grey
        cur_txt = font_sm.render(f"now: {current_rate:.0f}/hr", True, now_color)
        surface.blit(cur_txt, (gx + gw + 6, gy + 2))
        if not live_stable:
            st_txt = font_sm.render("stabilising…", True, grey)
            surface.blit(st_txt, (gx + gw + 6, gy + 34))
    # The ACTIVE configuration's settled average (matches its flat line)
    if active_avg is not None:
        avg_txt = font_sm.render(f"avg: {active_avg:.0f}/hr", True, avg_color)
    else:
        avg_txt = font_sm.render("avg: settling…", True, grey)
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
    picks_history: dict[str, list[tuple[float, float]]] | None = None,
    hover_pillar: str | None = None,
    drag_pillar: str | None = None,
    restart_marks: list[tuple[float, str]] | None = None,
    panel_scroll: int = 0,
) -> dict[str, pygame.Rect]:
    """Full frame render; returns clickable strategy-toggle hitboxes."""
    screen.fill(BG_COLOR)

    layer_order = [
        TileType.AISLE_RACK, TileType.RACKING, TileType.AGV_SPAWN,
        TileType.BOX_DEPOT, TileType.PACKOFF,
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

    # Light-grey SKU numbers at their slots — visual proof of the active
    # slotting strategy's placement
    draw_sku_numbers(screen)

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
    picker_counts = None
    if pickers is not None:
        picker_counts = {}
        for p in pickers.all_pickers():
            picker_counts[p.station_id] = picker_counts.get(p.station_id, 0) + 1
    draw_labels(
        screen, font_sm, font_md,
        station_fill=station_fill, eta_forecast=eta_forecast,
        picker_counts=picker_counts,
    )

    # Movable-pillar drag affordance (dynamic highway)
    draw_pillar_handles(
        screen, font_sm, hover_pillar=hover_pillar, drag_pillar=drag_pillar,
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
        picks_history=picks_history,
        restart_marks=restart_marks,
        carts=carts,
        agvs=agvs,
        picker_counts=picker_counts,
        pickers=pickers,
    )

    return draw_metrics_panel(
        screen, font_sm, font_md, agvs or [], carts or [],
        dispatcher, sim_elapsed, time_scale, paused, auto_spawn,
        selected_agv=selected_agv, scroll=panel_scroll,
    )
