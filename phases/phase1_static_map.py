#!/usr/bin/env python3
"""
AGV Warehouse Simulation - Phase 1: Static Map Display
======================================================
Renders the warehouse layout as a static map using Pygame,
matching the reference image.

Key layout facts:
  - LEFT side: ONE highway going down, stations alternate sides
    S1 = outer (left), S2 = inner (right), S3 = outer, S4 = inner
  - RIGHT side: ONE highway going up, stations alternate sides
    S5 = outer (right), S6 = inner (left), S7 = outer, S8 = inner,
    S9 = outer (right).  Single highway throughout.
  - Anti-clockwise loop:
    Spawn → right along North Hwy → down col 9 (S1-S4) →
    right along East Hwy → up col 38 (S5-S9) →
    right to Pack-off → left back to Box Depot → repeat
  - Parking on the OPPOSITE side of each station.

Run:  source venv/bin/activate && python3 phases/phase1_static_map.py
Quit: Press Q or close the window.
"""

import pygame
import sys
from enum import Enum

# ============================================================
# CONSTANTS
# ============================================================
TILE_SIZE = 25          # Each tile is 25x25 pixels
GRID_COLS = 60          # 60 columns  (x: 0-59, left to right)
GRID_ROWS = 40          # 40 rows     (y: 0-39, top to bottom)
WINDOW_WIDTH  = GRID_COLS * TILE_SIZE   # 1500 px
WINDOW_HEIGHT = GRID_ROWS * TILE_SIZE   # 1000 px
FPS = 30

# ============================================================
# TILE TYPES
# ============================================================
class TileType(Enum):
    EMPTY        = "empty"
    HIGHWAY      = "highway"        # Blue circles - AGV travel path
    PARKING      = "parking"        # White squares - temp cart storage
    PICK_STATION = "pick_station"   # Yellow - cart dwell spots at stations
    BOX_DEPOT    = "box_depot"      # Brown  - order loading area
    PACKOFF      = "packoff"        # Purple - pack-off conveyor
    AGV_SPAWN    = "agv_spawn"      # Gray   - AGV starting area
    CART_SPAWN   = "cart_spawn"     # Light purple - cart starting area
    RACKING      = "racking"        # Light yellow - shelving / pallet storage

# ============================================================
# COLOURS  (RGB)
# ============================================================
TILE_COLORS = {
    TileType.EMPTY:        (220, 225, 230),
    TileType.HIGHWAY:      (100, 190, 240),
    TileType.PARKING:      (255, 255, 255),
    TileType.PICK_STATION: (255, 200, 50),
    TileType.BOX_DEPOT:    (170, 135, 75),
    TileType.PACKOFF:      (175, 165, 225),
    TileType.AGV_SPAWN:    (155, 155, 155),
    TileType.CART_SPAWN:   (195, 155, 225),
    TileType.RACKING:      (255, 242, 185),
}
BG_COLOR       = (210, 215, 222)
OUTLINE_COLOR  = (175, 180, 188)
LABEL_COLOR    = (35, 35, 35)
LABEL_BG       = (255, 255, 255)

# ============================================================
# STATION CAPACITIES
# ============================================================
STATIONS = {
    "S1": 5, "S2": 4, "S3": 4, "S4": 4,
    "S5": 3, "S6": 4, "S7": 4, "S8": 4, "S9": 4,
    "Box_Depot": 8, "Pack_off": 4,
}

# ============================================================
# TILE CLASS
# ============================================================
class Tile:
    """One square on the warehouse grid."""
    def __init__(self, x, y, tile_type, station_id=None):
        self.x = x
        self.y = y
        self.tile_type = tile_type
        self.station_id = station_id

# ============================================================
# KEY LAYOUT CONSTANTS  (column / row positions)
# ============================================================
# Highways
LEFT_HWY_COL   = 9     # single highway down the left section
RIGHT_HWY_COL  = 38    # single highway up the right section
NORTH_HWY_ROW  = 7     # horizontal highway across the top
EAST_HWY_ROW   = 38    # horizontal highway across the bottom

# ============================================================
# MAP BUILDER
# ============================================================
def build_map():
    """
    Create the full warehouse map.
    Returns dict  { (x, y): Tile, ... }
    """
    tiles = {}

    # ----- helper functions -----
    def put(x, y, tt, sid=None):
        tiles[(x, y)] = Tile(x, y, tt, sid)

    def fill_rect(x1, y1, x2, y2, tt, sid=None):
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                put(x, y, tt, sid)

    def hline(x1, x2, y, tt, sid=None):
        for x in range(x1, x2 + 1):
            put(x, y, tt, sid)

    def vline(x, y1, y2, tt, sid=None):
        for y in range(y1, y2 + 1):
            put(x, y, tt, sid)

    # ==========================================================
    # 1.  AGV SPAWN  (top-left, cols 1-8, rows 0-6)
    # ==========================================================
    fill_rect(1, 0, 8, 6, TileType.AGV_SPAWN)

    # ==========================================================
    # 2.  CART SPAWN  (left edge, rows 7-8)
    # ==========================================================
    put(0, 7, TileType.CART_SPAWN)
    put(0, 8, TileType.CART_SPAWN)

    # ==========================================================
    # 3.  BOX DEPOT  (top-centre, brown rectangle)
    # ==========================================================
    fill_rect(14, 1, 24, 4, TileType.BOX_DEPOT, "Box_Depot")
    # 8 dock spots below the depot
    for i in range(8):
        put(15 + i, 5, TileType.PARKING, "Box_Depot")
    # short connectors from docks down to North Highway
    for i in range(8):
        put(15 + i, 6, TileType.HIGHWAY)

    # ==========================================================
    # 4.  PACK-OFF CONVEYOR  (top-right, purple rectangle)
    # ==========================================================
    fill_rect(47, 1, 54, 3, TileType.PACKOFF, "Pack_off")
    # 4 dock spots
    for i in range(4):
        put(49 + i, 4, TileType.PARKING, "Pack_off")
    # connectors to North Highway
    for i in range(4):
        vline(49 + i, 5, 6, TileType.HIGHWAY)

    # ==========================================================
    # 5.  NORTH HIGHWAY  (row 7, full width)
    #     Two-lane section from col 39 to col 57 (rows 7 & 8)
    #     for the Pack-off return path.
    # ==========================================================
    hline(1, 57, NORTH_HWY_ROW, TileType.HIGHWAY)
    hline(39, 57, NORTH_HWY_ROW + 1, TileType.HIGHWAY)   # 2nd lane

    # ==========================================================
    # 6.  LEFT SECTION  –  SINGLE highway at col 9
    # ==========================================================
    vline(LEFT_HWY_COL, 8, EAST_HWY_ROW, TileType.HIGHWAY)

    # ==========================================================
    # 7.  EAST HIGHWAY  (row 38)
    # ==========================================================
    hline(LEFT_HWY_COL, RIGHT_HWY_COL, EAST_HWY_ROW, TileType.HIGHWAY)

    # ==========================================================
    # 8.  RIGHT SECTION  –  SINGLE highway at col 38  (full length)
    #     goes from East Highway (row 38) all the way up to row 8,
    #     then connects to North Highway at row 7.
    # ==========================================================
    vline(RIGHT_HWY_COL, 8, EAST_HWY_ROW, TileType.HIGHWAY)

    # ==========================================================
    # 10. LEFT-SIDE STATIONS  (single highway at col 9)
    #     S1 = outer (LEFT),  S2 = inner (RIGHT)
    #     S3 = outer (LEFT),  S4 = inner (RIGHT)
    # ==========================================================

    # S1 – LEFT of highway, rows 10-14, 5 spots
    fill_rect(4, 10, 7, 14, TileType.RACKING, "S1")
    for y in range(10, 15):                         # 5 pick spots
        put(8, y, TileType.PICK_STATION, "S1")

    # S2 – RIGHT of highway, rows 17-20, 4 spots
    fill_rect(11, 17, 16, 20, TileType.RACKING, "S2")
    for y in range(17, 21):                         # 4 pick spots
        put(10, y, TileType.PICK_STATION, "S2")

    # S3 – LEFT of highway, rows 23-26, 4 spots
    fill_rect(4, 23, 7, 26, TileType.RACKING, "S3")
    for y in range(23, 27):
        put(8, y, TileType.PICK_STATION, "S3")

    # S4 – RIGHT of highway, rows 29-32, 4 spots
    fill_rect(11, 29, 16, 32, TileType.RACKING, "S4")
    for y in range(29, 33):
        put(10, y, TileType.PICK_STATION, "S4")

    # ==========================================================
    # 11. RIGHT-SIDE STATIONS  (single highway at col 38)
    #     Going UP from East Highway:
    #     S5 = RIGHT (outer), S6 = LEFT (inner)
    #     S7 = RIGHT,         S8 = LEFT
    # ==========================================================

    # S5 – RIGHT of highway, rows 34-36, 3 spots
    fill_rect(40, 34, 44, 36, TileType.RACKING, "S5")
    for y in range(34, 37):
        put(39, y, TileType.PICK_STATION, "S5")

    # S6 – LEFT of highway, rows 28-31, 4 spots
    fill_rect(32, 28, 36, 31, TileType.RACKING, "S6")
    for y in range(28, 32):
        put(37, y, TileType.PICK_STATION, "S6")

    # S7 – RIGHT of highway, rows 22-25, 4 spots
    fill_rect(40, 22, 44, 25, TileType.RACKING, "S7")
    for y in range(22, 26):
        put(39, y, TileType.PICK_STATION, "S7")

    # S8 – LEFT of highway, rows 16-19, 4 spots
    fill_rect(32, 16, 36, 19, TileType.RACKING, "S8")
    for y in range(16, 20):
        put(37, y, TileType.PICK_STATION, "S8")

    # ==========================================================
    # 12. S9 – RIGHT (outer) side of col 38, rows 10-13, 4 spots
    #     Same pattern as S5, S7 (outer/right side)
    # ==========================================================
    fill_rect(40, 10, 44, 13, TileType.RACKING, "S9")
    for y in range(10, 14):
        put(39, y, TileType.PICK_STATION, "S9")

    # ==========================================================
    # 13. PARKING  –  opposite side of each station
    #     Where there are pick-station tiles on one side,
    #     place parking tiles on the OTHER side of the highway.
    # ==========================================================

    # Left section: stations alternate LEFT / RIGHT of col 9
    # S1 is LEFT  (col 8, rows 10-14) → parking RIGHT (col 10)
    for y in range(10, 15):
        put(10, y, TileType.PARKING)
    # S2 is RIGHT (col 10, rows 17-20) → parking LEFT (col 8)
    for y in range(17, 21):
        put(8, y, TileType.PARKING)
    # S3 is LEFT  (col 8, rows 23-26) → parking RIGHT (col 10)
    for y in range(23, 27):
        put(10, y, TileType.PARKING)
    # S4 is RIGHT (col 10, rows 29-32) → parking LEFT (col 8)
    for y in range(29, 33):
        put(8, y, TileType.PARKING)

    # Right section: stations alternate RIGHT / LEFT of col 38
    # S5 is RIGHT (col 39, rows 34-36) → parking LEFT (col 37)
    for y in range(34, 37):
        put(37, y, TileType.PARKING)
    # S6 is LEFT  (col 37, rows 28-31) → parking RIGHT (col 39)
    for y in range(28, 32):
        put(39, y, TileType.PARKING)
    # S7 is RIGHT (col 39, rows 22-25) → parking LEFT (col 37)
    for y in range(22, 26):
        put(37, y, TileType.PARKING)
    # S8 is LEFT  (col 37, rows 16-19) → parking RIGHT (col 39)
    for y in range(16, 20):
        put(39, y, TileType.PARKING)
    # S9 is RIGHT (col 39, rows 10-13) → parking LEFT (col 37)
    for y in range(10, 14):
        put(37, y, TileType.PARKING)

    # --- Gap rows: parking on both sides of highway (between stations) ---
    left_gap_rows = [9, 15, 16, 21, 22, 27, 28, 33, 34, 35, 36, 37]
    for y in left_gap_rows:
        for x in (8, 10):
            if (x, y) not in tiles:
                put(x, y, TileType.PARKING)

    right_gap_rows = [9, 14, 15, 20, 21, 26, 27, 32, 33, 37]
    for y in right_gap_rows:
        for x in (37, 39):
            if (x, y) not in tiles:
                put(x, y, TileType.PARKING)

    # --- Along North Highway (one row above, row 6) ---
    for x in [10, 12, 26, 28, 30, 40, 55]:
        if (x, 6) not in tiles:
            put(x, 6, TileType.PARKING)

    # --- Along East Highway (one row below, row 39) ---
    for x in [12, 18, 24, 30, 36]:
        put(x, 39, TileType.PARKING)

    return tiles

# ============================================================
# RENDERING
# ============================================================
def draw_tile(surface, tile):
    """Draw one tile at its grid position."""
    px = tile.x * TILE_SIZE
    py = tile.y * TILE_SIZE
    color = TILE_COLORS[tile.tile_type]
    rect = pygame.Rect(px, py, TILE_SIZE, TILE_SIZE)

    if tile.tile_type == TileType.HIGHWAY:
        # filled circle on neutral background
        pygame.draw.rect(surface, BG_COLOR, rect)
        cx = px + TILE_SIZE // 2
        cy = py + TILE_SIZE // 2
        pygame.draw.circle(surface, color, (cx, cy), TILE_SIZE // 2 - 3)

    elif tile.tile_type == TileType.PARKING:
        # purple for depot/packoff docks, white for normal parking
        if tile.station_id in ("Box_Depot", "Pack_off"):
            pygame.draw.rect(surface, TILE_COLORS[TileType.PACKOFF], rect)
        else:
            pygame.draw.rect(surface, color, rect)
        pygame.draw.rect(surface, OUTLINE_COLOR, rect, 1)

    elif tile.tile_type == TileType.PICK_STATION:
        # bold yellow with darker border
        pygame.draw.rect(surface, color, rect)
        pygame.draw.rect(surface, (200, 160, 30), rect, 1)

    else:
        pygame.draw.rect(surface, color, rect)


def draw_labels(surface, font_sm, font_md):
    """Draw station names, section labels, and capacity placeholders."""

    def label(text, cx, cy, font=None, bg=True):
        """Render centred text at pixel position (cx, cy)."""
        f = font or font_sm
        txt = f.render(text, True, LABEL_COLOR)
        r = txt.get_rect(center=(cx, cy))
        if bg:
            pad = 3
            bgr = r.inflate(pad * 2, pad * 2)
            pygame.draw.rect(surface, LABEL_BG, bgr)
            pygame.draw.rect(surface, OUTLINE_COLOR, bgr, 1)
        surface.blit(txt, r)

    ts = TILE_SIZE

    # --- Left-side station labels ---
    # S1: racking cols 4-7, rows 10-14 → centre ≈ (5.5, 12)
    label("S1",   int(5.5*ts+ts/2),  12*ts+ts//2, font_md)
    label("0/5",  int(5.5*ts+ts/2),  13*ts+ts//2)
    # S2: racking cols 11-16, rows 17-20 → centre ≈ (13.5, 18.5)
    label("S2",   int(13.5*ts+ts/2), int(18*ts+ts/2), font_md)
    label("0/4",  int(13.5*ts+ts/2), int(19*ts+ts/2))
    # S3: racking cols 4-7, rows 23-26
    label("S3",   int(5.5*ts+ts/2),  int(24*ts+ts/2), font_md)
    label("0/4",  int(5.5*ts+ts/2),  int(25*ts+ts/2))
    # S4: racking cols 11-16, rows 29-32
    label("S4",   int(13.5*ts+ts/2), int(30*ts+ts/2), font_md)
    label("0/4",  int(13.5*ts+ts/2), int(31*ts+ts/2))

    # --- Right-side station labels ---
    # S5: racking cols 40-44, rows 34-36
    label("S5",   42*ts+ts//2, 35*ts+ts//2, font_md)
    label("0/3",  42*ts+ts//2, 36*ts+ts//2)
    # S6: racking cols 32-36, rows 28-31
    label("S6",   34*ts+ts//2, 29*ts+ts//2, font_md)
    label("0/4",  34*ts+ts//2, 30*ts+ts//2)
    # S7: racking cols 40-44, rows 22-25
    label("S7",   42*ts+ts//2, 23*ts+ts//2, font_md)
    label("0/4",  42*ts+ts//2, 24*ts+ts//2)
    # S8: racking cols 32-36, rows 16-19
    label("S8",   34*ts+ts//2, 17*ts+ts//2, font_md)
    label("0/4",  34*ts+ts//2, 18*ts+ts//2)
    # S9: racking cols 40-44, rows 10-13  (RIGHT/outer, same as S5, S7)
    label("S9",   42*ts+ts//2, 11*ts+ts//2, font_md)
    label("0/4",  42*ts+ts//2, 12*ts+ts//2)

    # --- Box Depot ---
    label("Box Depot", 19*ts+ts//2, int(2.5*ts), font_md)
    label("0/8",       19*ts+ts//2, int(3.5*ts))

    # --- Pack-off ---
    label("Packoff Conveyor", int(50.5*ts), int(1.5*ts), font_md)
    label("0/4",               int(50.5*ts), int(2.5*ts))

    # --- Section labels (no background box) ---
    label("South Pallets",  5*ts,  36*ts, font_sm, bg=False)
    label("North Pallets", 14*ts,  36*ts, font_sm, bg=False)

    label("North Highway", 35*ts, NORTH_HWY_ROW*ts+ts//2, font_sm, bg=False)
    label("East Highway",  25*ts, EAST_HWY_ROW*ts+ts//2,  font_sm, bg=False)

    label("AGV Spawn",  5*ts, 3*ts, font_sm)
    label("Cart Spawn", int(3*ts), int(9.5*ts), font_sm)


def render(screen, tiles, font_sm, font_md):
    """Full frame render: background → tiles (layered) → labels."""
    screen.fill(BG_COLOR)

    # Draw tiles in layer order (bottom layers first)
    layer_order = [
        TileType.RACKING,
        TileType.AGV_SPAWN,
        TileType.BOX_DEPOT,
        TileType.PACKOFF,
        TileType.CART_SPAWN,
        TileType.PARKING,
        TileType.PICK_STATION,
        TileType.HIGHWAY,
    ]
    by_type = {tt: [] for tt in layer_order}
    for tile in tiles.values():
        if tile.tile_type in by_type:
            by_type[tile.tile_type].append(tile)

    for tt in layer_order:
        for tile in by_type[tt]:
            draw_tile(screen, tile)

    draw_labels(screen, font_sm, font_md)


# ============================================================
# MAIN
# ============================================================
def main():
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("AGV Warehouse Simulation  –  Phase 1: Static Map")
    clock = pygame.time.Clock()

    font_sm = pygame.font.SysFont("Arial", 11)
    font_md = pygame.font.SysFont("Arial", 14, bold=True)

    tiles = build_map()

    print(f"Map built: {len(tiles)} tiles")
    print(f"Window:    {WINDOW_WIDTH}x{WINDOW_HEIGHT} px")
    print(f"Grid:      {GRID_COLS}x{GRID_ROWS}  ({TILE_SIZE}px tiles)")
    print("Press Q or close window to quit.")

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_q, pygame.K_ESCAPE):
                    running = False

        render(screen, tiles, font_sm, font_md)
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
