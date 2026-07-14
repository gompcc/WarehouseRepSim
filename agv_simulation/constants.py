from .enums import TileType

# ============================================================
# CONSTANTS
# ============================================================
TILE_SIZE = 12          # Each tile is 12x12 pixels (1 tile = 1 metre);
                        # sized so the window fits a 13" MacBook Pro
                        # (1440x900 logical) with the side panel visible
GRID_COLS = 86          # 86 columns (x: 0-85). Cols 0-13 = west aisle bank,
                        # 14-73 = legacy layout shifted +14, 74-85 = east bank
GRID_ROWS = 40          # 40 rows     (y: 0-39, top to bottom)
MAP_WIDTH     = GRID_COLS * TILE_SIZE   # 1032 px (map area)
MAP_HEIGHT    = GRID_ROWS * TILE_SIZE   # 480 px
PANEL_WIDTH   = 300
THROUGHPUT_STRIP_H = 80  # live orders/hr graph strip under the map
WINDOW_WIDTH  = MAP_WIDTH + PANEL_WIDTH        # 1332 px total
WINDOW_HEIGHT = MAP_HEIGHT + THROUGHPUT_STRIP_H  # 560 px
FPS = 30

SPEED_STEPS = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]

# Optimal fleet (AGVs, carts) per dispatch-strategy combo, keyed by
# (eta_reservations, global_assignment). Flipping a GUI toggle retargets
# the live fleet to the new combo's optimum via Environment.retarget_fleet.
# PROVISIONAL values pending the per-combo fleet screen under the current
# demand model (experiments/run_fleet_optimization.py refresh).
OPTIMAL_FLEET: dict[tuple[bool, bool], tuple[int, int]] = {
    (False, False): (10, 25),
    (True, False): (10, 25),
    (False, True): (10, 25),
    (True, True): (10, 25),
}
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
    TileType.AISLE_RACK:   (52, 52, 60),
}
BG_COLOR       = (210, 215, 222)
OUTLINE_COLOR  = (175, 180, 188)
LABEL_COLOR    = (35, 35, 35)
LABEL_BG       = (255, 255, 255)

# AGV constants
TILE_TRAVEL_TIME = 1.0      # seconds per tile
AGV_SPEED        = 1.0      # tiles per second (= 1 / TILE_TRAVEL_TIME)
AGV_COLOR        = (255, 60, 60)
AGV_SPAWN_TILE   = (15, 7)  # leftmost North Highway tile at spawn exit

# Cart constants (carts spawn at Box Depot tiles — see Environment.spawn_cart)
PICKUP_TIME  = 5.0          # seconds to pick up a cart
DROPOFF_TIME = 5.0          # seconds to drop off a cart
CART_COLOR_SPAWNED    = (255, 255, 255)  # white
CART_COLOR_IN_TRANSIT = (60, 200, 60)    # green
CART_COLOR_IDLE       = (80, 140, 255)   # blue

BOX_DEPOT_TIME     = 60.0   # seconds processing at box depot
PACKOFF_TIME       = 20.0   # seconds processing at pack-off
# (The old flat PICK_TIME_PER_ITEM=90s rule is gone: station dwell is fully
#  picker-gated — see PRD §14.6 and picker.py.)

# Picker & product aisle model (PRD Section 14)
NUM_SKUS            = 2000   # products, each with one pick slot in the aisles
METERS_PER_TILE     = 1.0    # walking scale: 1 tile = 1 metre
RACK_LEVELS         = 2      # bi-level racking
PICKERS_PER_STATION = 1      # human pickers serving each S station
PICKER_WALK_SPEED   = 1.4    # m/s
PICK_GRAB_TIME      = 10.0   # seconds to locate/grab one SKU line at the slot
PICKS_PER_VISIT_MEAN = 4.0   # shadow-mode fallback: lines sampled for a cart…
PICKS_PER_VISIT_SD   = 2.0   # …without an order (GUI-spawned), max(1, round(N))
ORDER_LINES_MEAN     = 20.0  # lines per order: max(1, round(N(mean, sd))),
ORDER_LINES_SD       = 9.0   # sampled popularity-weighted in SKU space
CART_COLOR_PROCESSING = (255, 165, 0)   # orange
CART_COLOR_WAITING    = (180, 100, 255) # purple — buffered, waiting for station
CART_COLOR_COMPLETED  = (200, 50, 50)   # red

BLOCK_TIMEOUT    = 1.5   # seconds blocked before attempting re-route
REROUTE_COOLDOWN = 1.0   # min gap between re-route attempts
JOB_CANCEL_TIMEOUT = 30.0  # seconds blocked before cancelling a non-carrying job
MAX_CONCURRENT_DISPATCHES = 12  # max AGVs dispatched at once (prevents highway gridlock)

# Pre-load defaults
PRELOAD_AGV_COUNT      = 10
PRELOAD_CART_COUNT     = 25
PRELOAD_SPAWN_INTERVAL = 5.0   # sim-seconds between pre-load cart spawns

# Environment audit
STUCK_WARN_SECONDS = 300.0  # no cart progress for this long → stuck event

# ============================================================
# KEY LAYOUT CONSTANTS  (column / row positions)
# ============================================================
# Highways
LEFT_HWY_COL   = 23    # single highway down the left section
RIGHT_HWY_COL  = 52    # single highway up the right section
NORTH_HWY_ROW  = 7     # horizontal highway across the top
EAST_HWY_ROW   = 38    # horizontal highway across the bottom
