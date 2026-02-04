from .enums import TileType

# ============================================================
# CONSTANTS
# ============================================================
TILE_SIZE = 20          # Each tile is 20x20 pixels
GRID_COLS = 60          # 60 columns  (x: 0-59, left to right)
GRID_ROWS = 40          # 40 rows     (y: 0-39, top to bottom)
MAP_WIDTH     = GRID_COLS * TILE_SIZE   # 1200 px (map area)
MAP_HEIGHT    = GRID_ROWS * TILE_SIZE  # 800 px
PANEL_WIDTH   = 300
WINDOW_WIDTH  = MAP_WIDTH + PANEL_WIDTH  # 1500 px total
WINDOW_HEIGHT = MAP_HEIGHT               # 800 px
FPS = 30

SPEED_STEPS = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]
AUTO_SPAWN_INTERVAL = 30.0   # sim-seconds between auto-spawned carts

# Panel color palette
PANEL_BG        = (30, 30, 40)
PANEL_TEXT       = (200, 200, 210)
PANEL_HEADER     = (140, 160, 255)
PANEL_SEPARATOR  = (60, 60, 80)
PANEL_GREEN      = (80, 220, 100)
PANEL_YELLOW     = (230, 200, 60)
PANEL_RED        = (230, 70, 70)

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

# Cart constants
CART_SPAWN_TILES = [(0, 7)]
PICKUP_TIME  = 5.0          # seconds to pick up a cart
DROPOFF_TIME = 5.0          # seconds to drop off a cart
CART_COLOR_SPAWNED    = (255, 255, 255)  # white
CART_COLOR_IN_TRANSIT = (60, 200, 60)    # green
CART_COLOR_IDLE       = (80, 140, 255)   # blue

BOX_DEPOT_TIME     = 45.0   # seconds processing at box depot
PICK_TIME_PER_ITEM = 90.0   # seconds per item at pick station
PACKOFF_TIME       = 60.0   # seconds processing at pack-off
CART_COLOR_PROCESSING = (255, 165, 0)   # orange
CART_COLOR_WAITING    = (180, 100, 255) # purple — buffered, waiting for station
CART_COLOR_COMPLETED  = (200, 50, 50)   # red

BLOCK_TIMEOUT    = 3.0   # seconds blocked before attempting re-route
REROUTE_COOLDOWN = 2.0   # min gap between re-route attempts
JOB_CANCEL_TIMEOUT = 30.0  # seconds blocked before cancelling a non-carrying job
MAX_CONCURRENT_DISPATCHES = 12  # max AGVs dispatched at once (prevents highway gridlock)

# ============================================================
# KEY LAYOUT CONSTANTS  (column / row positions)
# ============================================================
# Highways
LEFT_HWY_COL   = 9     # single highway down the left section
RIGHT_HWY_COL  = 38    # single highway up the right section
NORTH_HWY_ROW  = 7     # horizontal highway across the top
EAST_HWY_ROW   = 38    # horizontal highway across the bottom
