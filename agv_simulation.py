#!/usr/bin/env python3
"""
AGV Warehouse Simulation - Main Working File
=============================================
Active development file for the AGV warehouse simulation.
Renders the warehouse layout with AGV spawning, A* pathfinding,
click-to-send navigation, and return-to-spawn functionality.

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

Run:  source venv/bin/activate && python3 agv_simulation.py
Quit: Press Q or close the window.
"""

import pygame
import sys
import heapq
from enum import Enum

# ============================================================
# CONSTANTS
# ============================================================
TILE_SIZE = 20          # Each tile is 20x20 pixels
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

# AGV constants
TILE_TRAVEL_TIME = 1.0      # seconds per tile
AGV_SPEED        = 1.0      # tiles per second (= 1 / TILE_TRAVEL_TIME)
AGV_COLOR        = (255, 60, 60)
AGV_SPAWN_TILE   = (1, 7)   # leftmost North Highway tile at spawn exit

class AGVState(Enum):
    IDLE               = "idle"
    MOVING             = "moving"
    RETURNING_TO_SPAWN = "returning_to_spawn"

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
# DIRECTED GRAPH BUILDER
# ============================================================
def build_graph(tiles):
    """
    Build a directed adjacency dict {(x,y): set((nx,ny))} from the tile map.
    Encodes the anti-clockwise one-way loop for highway tiles, plus
    bidirectional access to/from stations and parking.
    """
    graph = {}

    # Classify every tile position
    highway_positions = set()
    non_highway_positions = set()
    for pos, tile in tiles.items():
        if tile.tile_type == TileType.HIGHWAY:
            highway_positions.add(pos)
        elif tile.tile_type in (TileType.PICK_STATION, TileType.PARKING,
                                TileType.AGV_SPAWN):
            non_highway_positions.add(pos)

    all_positions = highway_positions | non_highway_positions

    # Initialize empty adjacency sets
    for pos in all_positions:
        graph[pos] = set()

    # --- Junction special cases (checked first) ---
    junctions = {
        (9, 7):   [(1, 0), (0, 1), (-1, 0)],  # East + South + West (return entry)
        (9, 38):  [(1, 0)],              # East (corner)
        (38, 38): [(0, -1)],             # North (corner)
        (38, 8):  [(0, -1), (1, 0)],     # North + East (branch)
        (38, 7):  [(-1, 0)],             # West (join return)
        (57, 8):  [(0, -1)],             # North (end second lane)
    }

    # --- Segment direction rules ---
    def get_highway_directions(x, y):
        """Return list of (dx, dy) allowed moves for a highway tile."""
        # Junction overrides
        if (x, y) in junctions:
            return junctions[(x, y)]

        # North Hwy (spawn exit): row 7, cols 1-8 → East + West (return to spawn)
        if y == 7 and 1 <= x <= 8:
            return [(1, 0), (-1, 0)]

        # North Hwy (return): row 7, cols 10-57 → West
        if y == 7 and 10 <= x <= 57:
            dirs = [(-1, 0)]
            # Connector column overrides: also allow North
            if 15 <= x <= 22:   # Box Depot connectors
                dirs.append((0, -1))
            if 49 <= x <= 52:   # Pack-off connectors
                dirs.append((0, -1))
            return dirs

        # Left Highway: col 9, rows 8-38 → South
        if x == 9 and 8 <= y <= 38:
            return [(0, 1)]

        # East Highway: row 38, cols 9-38 → East
        if y == 38 and 9 <= x <= 38:
            return [(1, 0)]

        # Right Highway: col 38, rows 8-38 → North
        if x == 38 and 8 <= y <= 38:
            return [(0, -1)]

        # Second lane: row 8, cols 39-57 → East
        if y == 8 and 39 <= x <= 57:
            return [(1, 0)]

        # Connector columns (Box Depot cols 15-22, rows 5-6) → North + South
        if 15 <= x <= 22 and 5 <= y <= 6:
            return [(0, -1), (0, 1)]

        # Connector columns (Pack-off cols 49-52, rows 5-6) → North + South
        if 49 <= x <= 52 and 5 <= y <= 6:
            return [(0, -1), (0, 1)]

        # Default for any other highway tile: no directed movement
        return []

    # --- Build highway edges ---
    for pos in highway_positions:
        x, y = pos
        for dx, dy in get_highway_directions(x, y):
            neighbor = (x + dx, y + dy)
            if neighbor in all_positions:
                graph[pos].add(neighbor)

    # --- Non-highway tiles: allow all 4 cardinal directions ---
    for pos in non_highway_positions:
        x, y = pos
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            neighbor = (x + dx, y + dy)
            if neighbor in all_positions:
                graph[pos].add(neighbor)

    # --- Sidetrack edges: highway ↔ adjacent PICK_STATION, PARKING, or AGV_SPAWN ---
    for pos in highway_positions:
        x, y = pos
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            neighbor = (x + dx, y + dy)
            if neighbor in non_highway_positions:
                tile = tiles[neighbor]
                if tile.tile_type in (TileType.PICK_STATION, TileType.PARKING,
                                      TileType.AGV_SPAWN):
                    # Bidirectional: highway → station/spawn and back
                    graph[pos].add(neighbor)
                    graph[neighbor].add(pos)

    return graph


# ============================================================
# A* PATHFINDING
# ============================================================
def astar(graph, start, goal):
    """
    Standard A* with Manhattan distance heuristic and uniform edge cost = 1.
    Returns list of (x,y) from start to goal inclusive, or None if no path.
    """
    if start not in graph or goal not in graph:
        return None

    def h(node):
        return abs(node[0] - goal[0]) + abs(node[1] - goal[1])

    # (f_score, counter, node)
    counter = 0
    open_set = [(h(start), counter, start)]
    came_from = {}
    g_score = {start: 0}

    while open_set:
        f, _, current = heapq.heappop(open_set)

        if current == goal:
            # Reconstruct path
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path

        for neighbor in graph.get(current, set()):
            tentative_g = g_score[current] + 1
            if tentative_g < g_score.get(neighbor, float('inf')):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                counter += 1
                heapq.heappush(open_set, (tentative_g + h(neighbor), counter, neighbor))

    return None


# ============================================================
# AGV CLASS
# ============================================================
class AGV:
    _next_id = 1

    def __init__(self, pos):
        self.agv_id = AGV._next_id
        AGV._next_id += 1
        self.state = AGVState.IDLE
        self.pos = pos          # current tile (x, y)
        self.target = None      # destination tile or None
        self.path = []          # list of (x, y)
        self.path_index = 0     # index of current segment start
        self.path_progress = 0.0  # 0.0–1.0 progress between path[index] and path[index+1]

    def set_destination(self, goal, graph, tiles):
        """Plan a path to goal. Returns True if path found."""
        route = astar(graph, self.pos, goal)
        if route is None:
            return False
        self.path = route
        self.path_index = 0
        self.path_progress = 0.0
        self.target = goal
        self.state = AGVState.MOVING
        return True

    def return_to_spawn(self, graph, tiles):
        """Plan a path back to AGV_SPAWN_TILE. Returns True if path found."""
        route = astar(graph, self.pos, AGV_SPAWN_TILE)
        if route is None:
            return False
        self.path = route
        self.path_index = 0
        self.path_progress = 0.0
        self.target = AGV_SPAWN_TILE
        self.state = AGVState.RETURNING_TO_SPAWN
        return True

    def update(self, dt):
        """Advance along path by AGV_SPEED * dt."""
        if self.state == AGVState.IDLE or not self.path:
            return

        self.path_progress += AGV_SPEED * dt

        while self.path_progress >= 1.0 and self.path_index < len(self.path) - 1:
            self.path_progress -= 1.0
            self.path_index += 1
            self.pos = self.path[self.path_index]

        # Arrived at destination?
        if self.path_index >= len(self.path) - 1:
            self.pos = self.path[-1]
            self.path_progress = 0.0
            self.state = AGVState.IDLE
            self.target = None
            self.path = []
            self.path_index = 0

    def get_render_pos(self):
        """Return interpolated pixel position (cx, cy) for rendering."""
        if not self.path or self.path_index >= len(self.path) - 1:
            # Static position
            px = self.pos[0] * TILE_SIZE + TILE_SIZE // 2
            py = self.pos[1] * TILE_SIZE + TILE_SIZE // 2
            return (px, py)

        # Interpolate between current and next tile
        cx, cy = self.path[self.path_index]
        nx, ny = self.path[self.path_index + 1]
        t = self.path_progress
        ix = cx + (nx - cx) * t
        iy = cy + (ny - cy) * t
        px = int(ix * TILE_SIZE + TILE_SIZE // 2)
        py = int(iy * TILE_SIZE + TILE_SIZE // 2)
        return (px, py)


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


def draw_agv(surface, agv, font):
    """Draw an AGV: red circle with black outline and white ID, plus green path dots."""
    # Draw remaining path as green dots
    if agv.path and agv.state != AGVState.IDLE:
        for i in range(agv.path_index + 1, len(agv.path)):
            tx, ty = agv.path[i]
            px = tx * TILE_SIZE + TILE_SIZE // 2
            py = ty * TILE_SIZE + TILE_SIZE // 2
            pygame.draw.circle(surface, (0, 200, 0), (px, py), 3)

    # Draw AGV circle
    cx, cy = agv.get_render_pos()
    radius = TILE_SIZE // 2 - 2
    pygame.draw.circle(surface, AGV_COLOR, (cx, cy), radius)
    pygame.draw.circle(surface, (0, 0, 0), (cx, cy), radius, 2)

    # Draw ID number
    id_text = font.render(str(agv.agv_id), True, (255, 255, 255))
    id_rect = id_text.get_rect(center=(cx, cy))
    surface.blit(id_text, id_rect)


def draw_ui(surface, font, agvs, selected_agv, time_scale=1.0):
    """Draw status text in bottom-left corner."""
    lines = []
    lines.append(f"AGVs: {len(agvs)}  |  Speed: {time_scale}x  |  A=spawn  R=return  TAB=cycle  Up/Down=speed")
    if selected_agv:
        sid = selected_agv.agv_id
        st = selected_agv.state.value
        pos = selected_agv.pos
        tgt = selected_agv.target
        lines.append(f"Selected: AGV {sid}  state={st}  pos={pos}  target={tgt}")
    else:
        lines.append("No AGV selected")

    y = WINDOW_HEIGHT - 10 - len(lines) * 18
    for line in lines:
        txt = font.render(line, True, (0, 0, 0))
        bg_rect = txt.get_rect(topleft=(10, y))
        bg_rect.inflate_ip(8, 4)
        pygame.draw.rect(surface, (255, 255, 255, 200), bg_rect)
        pygame.draw.rect(surface, (100, 100, 100), bg_rect, 1)
        surface.blit(txt, (10, y))
        y += 18


def render(screen, tiles, font_sm, font_md, agvs=None, selected_agv=None, time_scale=1.0):
    """Full frame render: background → tiles (layered) → labels → AGVs → UI."""
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

    # Draw AGVs on top
    if agvs:
        for agv in agvs:
            draw_agv(screen, agv, font_md)
        draw_ui(screen, font_sm, agvs, selected_agv, time_scale)


# ============================================================
# MAIN
# ============================================================
def verify_graph(graph, tiles):
    """Print graph stats and test a few key paths at startup."""
    print(f"\n--- Graph verification ---")
    print(f"Graph nodes: {len(graph)}")
    total_edges = sum(len(v) for v in graph.values())
    print(f"Graph edges: {total_edges}")

    # Test paths
    tests = [
        ("Spawn → S1 pick (8,12)", AGV_SPAWN_TILE, (8, 12)),
        ("Spawn → S5 pick (39,35)", AGV_SPAWN_TILE, (39, 35)),
        ("S1 pick (8,12) → Spawn (return)", (8, 12), AGV_SPAWN_TILE),
    ]
    for desc, start, goal in tests:
        path = astar(graph, start, goal)
        if path:
            print(f"  {desc}: {len(path)} tiles, "
                  f"~{len(path) * TILE_TRAVEL_TIME:.0f}s")
        else:
            print(f"  {desc}: NO PATH FOUND!")
    print("--- End verification ---\n")


def main():
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("AGV Warehouse Simulation")
    clock = pygame.time.Clock()

    font_sm = pygame.font.SysFont("Arial", 11)
    font_md = pygame.font.SysFont("Arial", 14, bold=True)

    tiles = build_map()
    graph = build_graph(tiles)

    print(f"Map built: {len(tiles)} tiles")
    print(f"Window:    {WINDOW_WIDTH}x{WINDOW_HEIGHT} px")
    print(f"Grid:      {GRID_COLS}x{GRID_ROWS}  ({TILE_SIZE}px tiles)")
    print("Controls: A=spawn AGV, R=return to spawn, TAB=cycle, Click=send to station")
    print("Press Q or close window to quit.")

    verify_graph(graph, tiles)

    # AGV state
    agvs = []
    selected_agv = None
    time_scale = 1.0        # multiplier for simulation speed

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
                    time_scale = min(time_scale * 2, 64.0)
                    print(f"Speed: {time_scale}x")

                elif event.key == pygame.K_DOWN:
                    time_scale = max(time_scale / 2, 0.25)
                    print(f"Speed: {time_scale}x")

                elif event.key == pygame.K_a:
                    # Spawn new AGV at spawn tile
                    new_agv = AGV(AGV_SPAWN_TILE)
                    agvs.append(new_agv)
                    selected_agv = new_agv
                    print(f"Spawned AGV {new_agv.agv_id} at {AGV_SPAWN_TILE}")

                elif event.key == pygame.K_r:
                    # Return selected idle AGV to spawn
                    if selected_agv and selected_agv.state == AGVState.IDLE:
                        if selected_agv.pos == AGV_SPAWN_TILE:
                            print(f"AGV {selected_agv.agv_id} already at spawn")
                        elif selected_agv.return_to_spawn(graph, tiles):
                            print(f"AGV {selected_agv.agv_id} returning to spawn "
                                  f"({len(selected_agv.path)} tiles)")
                        else:
                            print(f"AGV {selected_agv.agv_id}: no path to spawn!")

                elif event.key == pygame.K_TAB:
                    # Cycle selected AGV
                    if agvs:
                        if selected_agv is None:
                            selected_agv = agvs[0]
                        else:
                            idx = agvs.index(selected_agv)
                            selected_agv = agvs[(idx + 1) % len(agvs)]
                        print(f"Selected AGV {selected_agv.agv_id}")

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Left click: set destination for selected idle AGV
                if selected_agv and selected_agv.state == AGVState.IDLE:
                    mx, my = event.pos
                    gx = mx // TILE_SIZE
                    gy = my // TILE_SIZE
                    clicked = (gx, gy)
                    if clicked in tiles:
                        tile = tiles[clicked]
                        if tile.tile_type in (TileType.PICK_STATION, TileType.PARKING):
                            if selected_agv.set_destination(clicked, graph, tiles):
                                print(f"AGV {selected_agv.agv_id} → {clicked} "
                                      f"({tile.tile_type.value}"
                                      f"{' ' + tile.station_id if tile.station_id else ''}, "
                                      f"{len(selected_agv.path)} tiles)")
                            else:
                                print(f"AGV {selected_agv.agv_id}: no path to {clicked}!")

        # Update all AGVs
        sim_dt = dt * time_scale
        for agv in agvs:
            agv.update(sim_dt)

        render(screen, tiles, font_sm, font_md, agvs, selected_agv, time_scale)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
