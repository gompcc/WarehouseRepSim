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
import os
import contextlib
import heapq
import random
import time as _time
from enum import Enum

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
CART_COLOR_COMPLETED  = (200, 50, 50)   # red

BLOCK_TIMEOUT    = 3.0   # seconds blocked before attempting re-route
REROUTE_COOLDOWN = 2.0   # min gap between re-route attempts

class AGVState(Enum):
    IDLE               = "idle"
    MOVING             = "moving"
    RETURNING_TO_SPAWN = "returning_to_spawn"
    MOVING_TO_PICKUP   = "moving_to_pickup"
    PICKING_UP         = "picking_up"
    MOVING_TO_DROPOFF  = "moving_to_dropoff"
    DROPPING_OFF       = "dropping_off"

class CartState(Enum):
    SPAWNED              = "spawned"                # At spawn zone
    IN_TRANSIT           = "in_transit"             # Being carried by AGV
    IDLE                 = "idle"                   # Dropped off, waiting
    # Phase 4+ lifecycle states:
    TO_BOX_DEPOT         = "to_box_depot"
    AT_BOX_DEPOT         = "at_box_depot"
    IN_TRANSIT_TO_PICK   = "in_transit_to_pick"
    PICKING              = "picking"
    IN_TRANSIT_TO_PACKOFF = "in_transit_to_packoff"
    AT_PACKOFF           = "at_packoff"
    COMPLETED            = "completed"

class Cart:
    _next_id = 1

    def __init__(self, pos):
        self.cart_id = Cart._next_id
        Cart._next_id += 1
        self.pos = pos              # current tile (x, y)
        self.state = CartState.SPAWNED
        self.carried_by = None      # AGV instance or None
        self.order = None           # Order instance or None
        self.process_timer = 0.0    # countdown for station processing

    def update(self, dt):
        """Decrement process_timer when at a processing station."""
        if self.state in (CartState.AT_BOX_DEPOT, CartState.PICKING, CartState.AT_PACKOFF):
            if self.process_timer > 0:
                self.process_timer -= dt
                if self.process_timer < 0:
                    self.process_timer = 0.0

    def get_color(self):
        if self.state == CartState.SPAWNED:
            return CART_COLOR_SPAWNED
        elif self.state in (CartState.TO_BOX_DEPOT, CartState.IN_TRANSIT_TO_PICK,
                            CartState.IN_TRANSIT_TO_PACKOFF, CartState.IN_TRANSIT):
            return CART_COLOR_IN_TRANSIT
        elif self.state in (CartState.AT_BOX_DEPOT, CartState.PICKING, CartState.AT_PACKOFF):
            return CART_COLOR_PROCESSING
        elif self.state == CartState.COMPLETED:
            return CART_COLOR_COMPLETED
        else:
            return CART_COLOR_IDLE

class Order:
    _next_id = 1
    def __init__(self):
        self.order_id = Order._next_id; Order._next_id += 1
        length = random.randint(1, 9)
        self.picks = [random.randint(1, 9) for _ in range(length)]
        self.stations_to_visit = sorted(set(self.picks))
        self.completed_stations = []
    def items_at_station(self, station_num):
        return self.picks.count(station_num)
    def next_station(self):
        for s in self.stations_to_visit:
            if s not in self.completed_stations:
                return s
        return None
    def complete_station(self, station_num):
        self.completed_stations.append(station_num)
    def all_picked(self):
        return len(self.completed_stations) == len(self.stations_to_visit)


class JobType(Enum):
    PICKUP_TO_BOX_DEPOT = "pickup_to_box_depot"
    MOVE_TO_PICK        = "move_to_pick"
    MOVE_TO_PACKOFF     = "move_to_packoff"
    RETURN_TO_BOX_DEPOT = "return_to_box_depot"


class Job:
    _next_id = 1
    def __init__(self, job_type, cart, target_pos, station_id=None):
        self.job_id = Job._next_id; Job._next_id += 1
        self.job_type = job_type
        self.cart = cart
        self.target_pos = target_pos
        self.station_id = station_id   # "S3" for pick jobs
        self.assigned_agv = None


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
# DISPATCHER  –  orchestrates autonomous cart lifecycle
# ============================================================
class Dispatcher:
    def __init__(self, tiles):
        # Pre-compute station tile positions for quick lookup
        self._station_tiles = {}  # { (station_id, tile_type): [(x,y), ...] }
        for (x, y), tile in tiles.items():
            key = (tile.station_id, tile.tile_type)
            if tile.station_id:
                self._station_tiles.setdefault(key, []).append((x, y))
        self.pending_jobs = []
        self.active_jobs = []
        self.completed_orders = 0
        self._station_fill_cache = {}
        # Throughput tracking
        self.order_completion_times = []
        self.cart_start_times = {}   # { cart_id: sim_elapsed when spawned }
        self.cycle_times = []
        self._sim_elapsed = 0.0

    def _reserved_tiles(self, carts):
        """Return set of tiles occupied by stationary carts or targeted by jobs."""
        reserved = set()
        for c in carts:
            if c.carried_by is None:
                reserved.add(c.pos)
        for job in self.pending_jobs:
            reserved.add(job.target_pos)
        for job in self.active_jobs:
            reserved.add(job.target_pos)
        return reserved

    def get_station_fill(self, carts):
        """Return { station_id: (current, capacity, fill_rate) } for all stations."""
        reserved = self._reserved_tiles(carts)
        fill = {}
        for station_id, capacity in STATIONS.items():
            key = (station_id, TileType.PICK_STATION) if station_id.startswith("S") else (station_id, TileType.PARKING)
            positions = self._station_tiles.get(key, [])
            current = sum(1 for pos in positions if pos in reserved)
            fill[station_id] = (current, capacity, current / capacity if capacity > 0 else 0.0)
        return fill

    def _pick_best_station(self, remaining_stations, cart_pos, carts):
        """Pick the least-busy station from remaining_stations using fill rate tiers + distance."""
        fill = self.get_station_fill(carts)
        candidates = []
        for s in remaining_stations:
            sid = f"S{s}"
            current, capacity, rate = fill.get(sid, (0, 0, 1.0))
            if current >= capacity:
                continue
            priority = 1 if rate <= 0.50 else (2 if rate <= 0.75 else 3)
            station_tiles = self._station_tiles.get((sid, TileType.PICK_STATION), [])
            dist = abs(cart_pos[0] - station_tiles[0][0]) + abs(cart_pos[1] - station_tiles[0][1]) if station_tiles else float('inf')
            candidates.append((priority, dist, s))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][2]

    def _find_tile(self, station_id, tile_type, carts=None):
        """Return an unoccupied tile for station_id + tile_type, or None if full."""
        key = (station_id, tile_type)
        positions = self._station_tiles.get(key, [])
        if not positions:
            return None
        if carts is not None:
            reserved = self._reserved_tiles(carts)
            for pos in positions:
                if pos not in reserved:
                    return pos
            return None  # station full — cart must wait
        return positions[0]

    def _has_job(self, cart):
        """Check if cart already has a pending or active job."""
        for job in self.pending_jobs:
            if job.cart is cart:
                return True
        for job in self.active_jobs:
            if job.cart is cart:
                return True
        return False

    def _create_jobs(self, carts, graph, tiles):
        """Check carts and create jobs as needed (capacity-based station routing)."""
        for cart in carts:
            if self._has_job(cart):
                continue

            if cart.state == CartState.SPAWNED and cart.carried_by is None:
                target = self._find_tile("Box_Depot", TileType.PARKING, carts)
                if target:
                    job = Job(JobType.PICKUP_TO_BOX_DEPOT, cart, target)
                    self.pending_jobs.append(job)
                    self.cart_start_times[cart.cart_id] = self._sim_elapsed

            elif cart.state == CartState.AT_BOX_DEPOT and cart.process_timer <= 0:
                # Generate order if cart has none
                if cart.order is None:
                    cart.order = Order()
                    print(f"[Order #{cart.order.order_id}] Cart C{cart.cart_id}: "
                          f"picks={cart.order.picks}, "
                          f"stations={['S'+str(s) for s in cart.order.stations_to_visit]}")
                remaining = [s for s in cart.order.stations_to_visit
                             if s not in cart.order.completed_stations]
                ns = self._pick_best_station(remaining, cart.pos, carts)
                if ns is None:
                    ns = cart.order.next_station()
                if ns is not None:
                    sid = f"S{ns}"
                    target = self._find_tile(sid, TileType.PICK_STATION, carts)
                    if target:
                        job = Job(JobType.MOVE_TO_PICK, cart, target, station_id=sid)
                        self.pending_jobs.append(job)

            elif cart.state == CartState.PICKING and cart.process_timer <= 0:
                if cart.order:
                    remaining = [s for s in cart.order.stations_to_visit
                                 if s not in cart.order.completed_stations]
                    ns = self._pick_best_station(remaining, cart.pos, carts)
                    if ns is None:
                        ns = cart.order.next_station()
                    if ns is not None:
                        sid = f"S{ns}"
                        target = self._find_tile(sid, TileType.PICK_STATION, carts)
                        if target:
                            job = Job(JobType.MOVE_TO_PICK, cart, target, station_id=sid)
                            self.pending_jobs.append(job)
                    elif cart.order.all_picked():
                        target = self._find_tile("Pack_off", TileType.PARKING, carts)
                        if target:
                            job = Job(JobType.MOVE_TO_PACKOFF, cart, target)
                            self.pending_jobs.append(job)

            elif cart.state == CartState.AT_PACKOFF and cart.process_timer <= 0:
                target = self._find_tile("Box_Depot", TileType.PARKING, carts)
                if target:
                    job = Job(JobType.RETURN_TO_BOX_DEPOT, cart, target)
                    self.pending_jobs.append(job)

            elif cart.state == CartState.COMPLETED and cart.carried_by is None:
                target = self._find_tile("Box_Depot", TileType.PARKING, carts)
                if target:
                    job = Job(JobType.RETURN_TO_BOX_DEPOT, cart, target)
                    self.pending_jobs.append(job)

    def _assign_jobs(self, agvs, graph, tiles):
        """Assign pending jobs to free AGVs."""
        free_agvs = [a for a in agvs
                     if a.state == AGVState.IDLE
                     and a.current_job is None
                     and a.carrying_cart is None]
        assigned = []
        for job in self.pending_jobs:
            if not free_agvs:
                break
            best_agv = min(free_agvs, key=lambda a: abs(a.pos[0] - job.cart.pos[0]) + abs(a.pos[1] - job.cart.pos[1]))
            dist = abs(best_agv.pos[0] - job.cart.pos[0]) + abs(best_agv.pos[1] - job.cart.pos[1])
            if best_agv.pickup_cart(job.cart, graph, tiles):
                job.assigned_agv = best_agv
                best_agv.current_job = job
                self.active_jobs.append(job)
                assigned.append(job)
                free_agvs.remove(best_agv)
                print(f"[Dispatcher] AGV {best_agv.agv_id} assigned Job #{job.job_id} "
                      f"({job.job_type.value}) → pickup C{job.cart.cart_id} dist={dist}")
        for job in assigned:
            self.pending_jobs.remove(job)

    def _set_transit_state(self, job):
        """Set the cart's transit state based on job type."""
        mapping = {
            JobType.PICKUP_TO_BOX_DEPOT: CartState.TO_BOX_DEPOT,
            JobType.MOVE_TO_PICK:        CartState.IN_TRANSIT_TO_PICK,
            JobType.MOVE_TO_PACKOFF:     CartState.IN_TRANSIT_TO_PACKOFF,
            JobType.RETURN_TO_BOX_DEPOT: CartState.TO_BOX_DEPOT,
        }
        job.cart.state = mapping.get(job.job_type, CartState.IN_TRANSIT)

    def _complete_job(self, job):
        """Handle job completion after dropoff finishes."""
        cart = job.cart
        agv = job.assigned_agv

        if job.job_type == JobType.PICKUP_TO_BOX_DEPOT:
            cart.state = CartState.AT_BOX_DEPOT
            cart.process_timer = BOX_DEPOT_TIME
            print(f"[Dispatcher] C{cart.cart_id} arrived at Box Depot — processing {BOX_DEPOT_TIME}s")

        elif job.job_type == JobType.MOVE_TO_PICK:
            station_num = int(job.station_id[1:])
            items = cart.order.items_at_station(station_num) if cart.order else 1
            cart.state = CartState.PICKING
            cart.process_timer = PICK_TIME_PER_ITEM * items
            if cart.order:
                cart.order.complete_station(station_num)
            print(f"[Dispatcher] C{cart.cart_id} at {job.station_id} — "
                  f"picking {items} items ({cart.process_timer}s)")

        elif job.job_type == JobType.MOVE_TO_PACKOFF:
            cart.state = CartState.AT_PACKOFF
            cart.process_timer = PACKOFF_TIME
            print(f"[Dispatcher] C{cart.cart_id} at Pack-off — processing {PACKOFF_TIME}s")

        elif job.job_type == JobType.RETURN_TO_BOX_DEPOT:
            cart.state = CartState.AT_BOX_DEPOT
            cart.process_timer = BOX_DEPOT_TIME
            cart.order = None
            self.completed_orders += 1
            # Track cycle time
            start_t = self.cart_start_times.pop(cart.cart_id, None)
            if start_t is not None:
                cycle = self._sim_elapsed - start_t
                self.cycle_times.append(cycle)
                self.order_completion_times.append(self._sim_elapsed)
            print(f"[Dispatcher] C{cart.cart_id} returned to Box Depot — "
                  f"completed orders: {self.completed_orders}")

        # Clear job from AGV
        if agv:
            agv.current_job = None
        if job in self.active_jobs:
            self.active_jobs.remove(job)

    def _progress_jobs(self, graph, tiles):
        """Monitor active jobs and advance them through phases."""
        for job in list(self.active_jobs):
            agv = job.assigned_agv
            if agv is None:
                continue

            # Phase 1: AGV finished pickup (now IDLE and carrying cart)
            #          → set transit state + start dropoff to target
            if (agv.state == AGVState.IDLE
                    and agv.carrying_cart is not None
                    and agv.carrying_cart is job.cart):
                # Cart just picked up — set transit state and send to target
                self._set_transit_state(job)
                if agv.start_dropoff(job.target_pos, graph, tiles):
                    print(f"[Dispatcher] AGV {agv.agv_id} carrying C{job.cart.cart_id} "
                          f"→ {job.target_pos} ({len(agv.path)} tiles)")
                else:
                    print(f"[Dispatcher] AGV {agv.agv_id}: no path to {job.target_pos}!")

            # Phase 2: AGV finished dropoff (now IDLE, no cart)
            #          → complete the job (set station state + timer)
            elif (agv.state == AGVState.IDLE
                    and agv.carrying_cart is None
                    and job.cart.carried_by is None):
                self._complete_job(job)

    def _handle_blocked_agvs(self, agvs, graph, tiles):
        """Re-route AGVs that have been blocked too long, nudge idle blockers."""
        for agv in agvs:
            if not agv.is_blocked or agv.blocked_timer < BLOCK_TIMEOUT:
                continue

            # Identify the blocking tile and entity
            blocker = None
            if agv.path and agv.path_index < len(agv.path) - 1:
                next_tile = agv.path[agv.path_index + 1]
                for other in agvs:
                    if other is not agv and other.pos == next_tile:
                        blocker = other
                        break

            # --- Nudge idle blockers aside ---
            if (blocker and blocker.state == AGVState.IDLE
                    and blocker.current_job is None
                    and not blocker.carrying_cart):
                # Find nearest unoccupied parking or spawn tile to nudge to
                agv_positions = {a.pos for a in agvs}  # includes blocker's own tile
                best_tile = None
                best_dist = float('inf')
                for pos, tile in tiles.items():
                    if tile.tile_type in (TileType.PARKING, TileType.AGV_SPAWN):
                        if pos not in agv_positions:
                            d = abs(pos[0] - blocker.pos[0]) + abs(pos[1] - blocker.pos[1])
                            if d < best_dist:
                                best_dist = d
                                best_tile = pos
                if best_tile and blocker.set_destination(best_tile, graph, tiles):
                    print(f"[Collision] Nudged idle AGV {blocker.agv_id} "
                          f"from {blocker.pos} → {best_tile}")
                    agv.blocked_timer = 0.0   # give time for nudge
                continue  # skip reroute this tick — nudge may clear it

            # --- Skip reroute if blocker is moving (just queue behind it) ---
            if blocker and blocker.state not in (AGVState.IDLE,):
                continue

            # --- Attempt reroute ---
            agv.last_reroute += agv.blocked_timer
            if agv.last_reroute < REROUTE_COOLDOWN:
                continue
            if agv.reroute(graph, agvs, tiles):
                agv.last_reroute = 0.0
                print(f"[Collision] AGV {agv.agv_id} re-routed ({len(agv.path)} tiles)")
            else:
                agv.blocked_timer = 0.0
                agv.last_reroute = 0.0

    def get_station_tile_positions(self, station_id):
        """Return list of PICK_STATION tile positions for a given station."""
        return self._station_tiles.get((station_id, TileType.PICK_STATION), [])

    def update(self, carts, agvs, graph, tiles, sim_elapsed=0.0):
        """Main dispatcher tick — called each frame after AGV updates."""
        self._sim_elapsed = sim_elapsed
        self._station_fill_cache = self.get_station_fill(carts)
        self._create_jobs(carts, graph, tiles)
        self._assign_jobs(agvs, graph, tiles)
        self._progress_jobs(graph, tiles)
        self._handle_blocked_agvs(agvs, graph, tiles)

    def get_bottleneck_alerts(self, carts):
        """Return list of alert strings for current bottlenecks."""
        alerts = []
        fill = self._station_fill_cache or self.get_station_fill(carts)

        # Pack-off full or queue > 3
        po_cur, po_cap, po_rate = fill.get("Pack_off", (0, 4, 0.0))
        if po_cur >= po_cap:
            alerts.append("Pack-off FULL")
        elif len([j for j in self.pending_jobs + self.active_jobs
                  if j.job_type == JobType.MOVE_TO_PACKOFF]) > 3:
            alerts.append("Pack-off queue > 3")

        # Stations at 100% with carts waiting
        for i in range(1, 10):
            sid = f"S{i}"
            cur, cap, rate = fill.get(sid, (0, 0, 0.0))
            if cur >= cap and cap > 0:
                waiting = len([j for j in self.pending_jobs + self.active_jobs
                               if j.station_id == sid])
                if waiting > 0:
                    alerts.append(f"{sid} FULL ({waiting} waiting)")

        # Box Depot full with spawned carts
        bd_cur, bd_cap, bd_rate = fill.get("Box_Depot", (0, 8, 0.0))
        spawned_count = sum(1 for c in carts if c.state == CartState.SPAWNED)
        if bd_cur >= bd_cap and spawned_count > 0:
            alerts.append(f"Box Depot FULL ({spawned_count} spawned)")

        return alerts

    def get_throughput_stats(self, sim_elapsed):
        """Return dict with completed, avg_cycle, per_hour."""
        completed = self.completed_orders
        avg_cycle = (sum(self.cycle_times) / len(self.cycle_times)
                     if self.cycle_times else 0.0)
        per_hour = (completed / (sim_elapsed / 3600.0)
                    if sim_elapsed > 0 else 0.0)
        return {
            "completed": completed,
            "avg_cycle": avg_cycle,
            "per_hour": per_hour,
        }


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
    # 2.  CART SPAWN  (left edge, row 7 only)
    # ==========================================================
    put(0, 7, TileType.CART_SPAWN)

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
    #     Two-lane section from col 1 to col 9 (spawn ↔ junction)
    #       row 7 = outbound (East), row 8 = inbound (West)
    #     Two-lane section from col 39 to col 57 (Pack-off return)
    # ==========================================================
    hline(1, 57, NORTH_HWY_ROW, TileType.HIGHWAY)
    hline(1, 8, NORTH_HWY_ROW + 1, TileType.HIGHWAY)      # spawn inbound lane
    hline(39, 57, NORTH_HWY_ROW + 1, TileType.HIGHWAY)     # pack-off 2nd lane

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
                                TileType.AGV_SPAWN, TileType.CART_SPAWN):
            non_highway_positions.add(pos)

    all_positions = highway_positions | non_highway_positions

    # Initialize empty adjacency sets
    for pos in all_positions:
        graph[pos] = set()

    # --- Junction special cases (checked first) ---
    junctions = {
        (9, 7):   [(0, 1), (-1, 0)],     # South (outbound → left hwy) + West (return lane → spawn)
        (9, 8):   [(0, 1), (-1, 0)],     # South (left hwy continues) + West (inbound lane)
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

        # Outbound lane: row 7, cols 1-8 → East only
        if y == 7 and 1 <= x <= 8:
            return [(1, 0)]

        # Inbound lane: row 8, cols 1-8 → West only
        if y == 8 and 1 <= x <= 8:
            return [(-1, 0)]

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
                                      TileType.AGV_SPAWN, TileType.CART_SPAWN):
                    # Bidirectional: highway → station/spawn and back
                    graph[pos].add(neighbor)
                    graph[neighbor].add(pos)

    return graph


# ============================================================
# A* PATHFINDING
# ============================================================
def astar(graph, start, goal, blocked=None, tiles=None):
    """
    A* with Manhattan distance heuristic and weighted edge costs.
    Highway tiles cost 1, all other walkable tiles cost 10.
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
            if blocked and neighbor in blocked and neighbor != goal:
                continue
            if tiles and neighbor != goal:
                tile = tiles.get(neighbor)
                edge_cost = 1 if (tile and tile.tile_type == TileType.HIGHWAY) else 10
            else:
                edge_cost = 1
            tentative_g = g_score[current] + edge_cost
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
        self.carrying_cart = None   # Cart instance or None
        self.action_timer = 0.0     # countdown for pickup/dropoff
        self.current_job = None     # Job instance or None (managed by Dispatcher)
        self.blocked_timer = 0.0
        self.last_reroute  = 0.0
        self.is_blocked    = False
        self._just_rerouted = False

    def set_destination(self, goal, graph, tiles):
        """Plan a path to goal. Returns True if path found."""
        route = astar(graph, self.pos, goal, tiles=tiles)
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
        route = astar(graph, self.pos, AGV_SPAWN_TILE, tiles=tiles)
        if route is None:
            return False
        self.path = route
        self.path_index = 0
        self.path_progress = 0.0
        self.target = AGV_SPAWN_TILE
        self.state = AGVState.RETURNING_TO_SPAWN
        return True

    def pickup_cart(self, cart, graph, tiles):
        """Pathfind to cart's position, then pick it up. Returns True if path found."""
        route = astar(graph, self.pos, cart.pos, tiles=tiles)
        if route is None:
            return False
        self.path = route
        self.path_index = 0
        self.path_progress = 0.0
        self.target = cart.pos
        self.carrying_cart = cart    # remember which cart we're going to pick up
        self.state = AGVState.MOVING_TO_PICKUP
        return True

    def start_dropoff(self, goal, graph, tiles):
        """Pathfind to goal while carrying a cart. Returns True if path found."""
        route = astar(graph, self.pos, goal, tiles=tiles)
        if route is None:
            return False
        self.path = route
        self.path_index = 0
        self.path_progress = 0.0
        self.target = goal
        self.state = AGVState.MOVING_TO_DROPOFF
        return True

    def reroute(self, graph, agvs, tiles=None):
        """Re-plan path avoiding tiles occupied by other AGVs."""
        goal = self.target or (self.path[-1] if self.path else None)
        if goal is None:
            return False
        blocked = {a.pos for a in agvs if a is not self}
        route = astar(graph, self.pos, goal, blocked=blocked, tiles=tiles)
        if route is None:
            return False
        # Reject reroute if the first step is the same — would just block again
        old_next = (self.path[self.path_index + 1]
                    if self.path and self.path_index < len(self.path) - 1
                    else None)
        new_next = route[1] if len(route) > 1 else None
        if old_next and new_next and old_next == new_next:
            return False
        self.path = route
        self.path_index = 0
        self.path_progress = 0.0
        self.blocked_timer = 0.0
        self.is_blocked = False
        return True

    def update(self, dt, agvs=None, carts=None, graph=None, tiles=None):
        """Advance along path or count down action timers."""
        # --- Pickup timer ---
        if self.state == AGVState.PICKING_UP:
            self.action_timer -= dt
            if self.action_timer <= 0:
                self.action_timer = 0.0
                if self.carrying_cart:
                    self.carrying_cart.state = CartState.IN_TRANSIT
                    self.carrying_cart.carried_by = self
                    self.carrying_cart.pos = self.pos
                self.state = AGVState.IDLE
            return

        # --- Dropoff timer ---
        if self.state == AGVState.DROPPING_OFF:
            self.action_timer -= dt
            if self.action_timer <= 0:
                self.action_timer = 0.0
                if self.carrying_cart:
                    self.carrying_cart.state = CartState.IDLE
                    self.carrying_cart.carried_by = None
                    self.carrying_cart.pos = self.pos
                    self.carrying_cart = None
                self.state = AGVState.IDLE
            return

        # --- Movement ---
        if self.state == AGVState.IDLE or not self.path:
            return

        self.path_progress += AGV_SPEED * dt

        while self.path_progress >= 1.0 and self.path_index < len(self.path) - 1:
            next_tile = self.path[self.path_index + 1]

            # --- L1: collision check ---
            occupied = False
            # AGV-AGV
            if agvs:
                for other in agvs:
                    if other is not self and other.pos == next_tile:
                        occupied = True
                        break
            # Cart-cart: only block if THIS AGV is actually carrying a cart
            # (carrying_cart is set early in pickup_cart() to remember the
            #  target, but carried_by isn't set to self until pickup completes)
            if not occupied and carts and self.carrying_cart and self.carrying_cart.carried_by is self:
                for cart in carts:
                    if cart.carried_by is None and cart.pos == next_tile:
                        occupied = True
                        break
            if occupied:
                # Immediate reroute: try to find alt path avoiding blocked tile
                if graph and not self._just_rerouted:
                    blocked_tiles = {a.pos for a in agvs if a is not self}
                    alt = astar(graph, self.pos,
                                self.target or self.path[-1],
                                blocked=blocked_tiles, tiles=tiles)
                    if alt and len(alt) > 1:
                        if alt[1] != next_tile:
                            self.path = alt
                            self.path_index = 0
                            self.path_progress = min(self.path_progress, 0.99)
                            self._just_rerouted = True
                            self.is_blocked = False
                            self.blocked_timer = 0.0
                            continue  # retry with new path
                self.path_progress = 0.99   # hold just before boundary
                self.is_blocked = True
                self.blocked_timer += dt
                return

            # --- clear to advance ---
            self._just_rerouted = False
            self.is_blocked = False
            self.blocked_timer = 0.0
            self.path_progress -= 1.0
            self.path_index += 1
            self.pos = self.path[self.path_index]
            if self.carrying_cart and self.carrying_cart.state == CartState.IN_TRANSIT:
                self.carrying_cart.pos = self.pos

        # Arrived at destination?
        if self.path_index >= len(self.path) - 1:
            self.pos = self.path[-1]
            self.path_progress = 0.0
            self.target = None
            self.path = []
            self.path_index = 0
            self.is_blocked = False
            self.blocked_timer = 0.0
            self._just_rerouted = False
            # Cart follows on final snap
            if self.carrying_cart and self.carrying_cart.state == CartState.IN_TRANSIT:
                self.carrying_cart.pos = self.pos

            if self.state == AGVState.MOVING_TO_PICKUP:
                self.state = AGVState.PICKING_UP
                self.action_timer = PICKUP_TIME
            elif self.state == AGVState.MOVING_TO_DROPOFF:
                self.state = AGVState.DROPPING_OFF
                self.action_timer = DROPOFF_TIME
            else:
                self.state = AGVState.IDLE

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


def draw_labels(surface, font_sm, font_md, station_fill=None):
    """Draw station names, section labels, and live capacity indicators."""

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

    def capacity_label(station_id, cx, cy):
        """Render a color-coded capacity label from live station_fill data."""
        if station_fill and station_id in station_fill:
            current, capacity, rate = station_fill[station_id]
        else:
            capacity = STATIONS.get(station_id, 0)
            current, rate = 0, 0.0
        text = f"{current}/{capacity}"
        if rate <= 0.50:
            color = (30, 140, 30)     # green
        elif rate <= 0.75:
            color = (200, 160, 0)     # amber/yellow
        else:
            color = (200, 40, 40)     # red
        f = font_sm
        txt = f.render(text, True, color)
        r = txt.get_rect(center=(cx, cy))
        pad = 3
        bgr = r.inflate(pad * 2, pad * 2)
        pygame.draw.rect(surface, LABEL_BG, bgr)
        pygame.draw.rect(surface, OUTLINE_COLOR, bgr, 1)
        surface.blit(txt, r)

    ts = TILE_SIZE

    # --- Left-side station labels ---
    # S1: racking cols 4-7, rows 10-14 → centre ≈ (5.5, 12)
    label("S1",   int(5.5*ts+ts/2),  12*ts+ts//2, font_md)
    capacity_label("S1",  int(5.5*ts+ts/2),  13*ts+ts//2)
    # S2: racking cols 11-16, rows 17-20 → centre ≈ (13.5, 18.5)
    label("S2",   int(13.5*ts+ts/2), int(18*ts+ts/2), font_md)
    capacity_label("S2",  int(13.5*ts+ts/2), int(19*ts+ts/2))
    # S3: racking cols 4-7, rows 23-26
    label("S3",   int(5.5*ts+ts/2),  int(24*ts+ts/2), font_md)
    capacity_label("S3",  int(5.5*ts+ts/2),  int(25*ts+ts/2))
    # S4: racking cols 11-16, rows 29-32
    label("S4",   int(13.5*ts+ts/2), int(30*ts+ts/2), font_md)
    capacity_label("S4",  int(13.5*ts+ts/2), int(31*ts+ts/2))

    # --- Right-side station labels ---
    # S5: racking cols 40-44, rows 34-36
    label("S5",   42*ts+ts//2, 35*ts+ts//2, font_md)
    capacity_label("S5",  42*ts+ts//2, 36*ts+ts//2)
    # S6: racking cols 32-36, rows 28-31
    label("S6",   34*ts+ts//2, 29*ts+ts//2, font_md)
    capacity_label("S6",  34*ts+ts//2, 30*ts+ts//2)
    # S7: racking cols 40-44, rows 22-25
    label("S7",   42*ts+ts//2, 23*ts+ts//2, font_md)
    capacity_label("S7",  42*ts+ts//2, 24*ts+ts//2)
    # S8: racking cols 32-36, rows 16-19
    label("S8",   34*ts+ts//2, 17*ts+ts//2, font_md)
    capacity_label("S8",  34*ts+ts//2, 18*ts+ts//2)
    # S9: racking cols 40-44, rows 10-13  (RIGHT/outer, same as S5, S7)
    label("S9",   42*ts+ts//2, 11*ts+ts//2, font_md)
    capacity_label("S9",  42*ts+ts//2, 12*ts+ts//2)

    # --- Box Depot ---
    label("Box Depot", 19*ts+ts//2, int(2.5*ts), font_md)
    capacity_label("Box_Depot", 19*ts+ts//2, int(3.5*ts))

    # --- Pack-off ---
    label("Packoff Conveyor", int(50.5*ts), int(1.5*ts), font_md)
    capacity_label("Pack_off", int(50.5*ts), int(2.5*ts))

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

    # Orange outline ring when blocked
    if agv.is_blocked:
        pygame.draw.circle(surface, (255, 140, 0), (cx, cy), radius + 2, 2)

    # Draw ID number
    id_text = font.render(str(agv.agv_id), True, (255, 255, 255))
    id_rect = id_text.get_rect(center=(cx, cy))
    surface.blit(id_text, id_rect)


def draw_cart(surface, cart, font, carried_render_pos=None):
    """Draw a cart: colored rounded rect with black outline and C{id} text."""
    if carried_render_pos:
        # Carried cart: render at AGV's interpolated position, offset below
        cx, cy = carried_render_pos
        cy += 6  # slight offset below AGV center
    else:
        # Stationary cart: render at tile position
        cx = cart.pos[0] * TILE_SIZE + TILE_SIZE // 2
        cy = cart.pos[1] * TILE_SIZE + TILE_SIZE // 2

    w, h = 16, 10
    color = cart.get_color()
    rect = pygame.Rect(cx - w // 2, cy - h // 2, w, h)
    pygame.draw.rect(surface, color, rect, border_radius=2)
    pygame.draw.rect(surface, (0, 0, 0), rect, 1, border_radius=2)

    # Cart ID label
    id_text = font.render(f"C{cart.cart_id}", True, (0, 0, 0))
    id_rect = id_text.get_rect(center=(cx, cy))
    surface.blit(id_text, id_rect)


def draw_ui(surface, font, agvs, selected_agv, time_scale=1.0, carts=None, dispatcher=None):
    """Draw status text in bottom-left corner."""
    lines = []
    cart_count = len(carts) if carts else 0
    disp_info = ""
    if dispatcher:
        disp_info = (f"  |  Jobs: {len(dispatcher.pending_jobs)} pending, "
                     f"{len(dispatcher.active_jobs)} active  |  "
                     f"Orders completed: {dispatcher.completed_orders}")
    lines.append(f"AGVs: {len(agvs)}  Carts: {cart_count}  |  Speed: {time_scale}x  |  "
                 f"A=spawn  C=cart  P=pickup  R=return  TAB=cycle{disp_info}")
    if selected_agv:
        sid = selected_agv.agv_id
        st = selected_agv.state.value
        pos = selected_agv.pos
        tgt = selected_agv.target
        carrying = f"  carrying=C{selected_agv.carrying_cart.cart_id}" if selected_agv.carrying_cart else ""
        timer_str = ""
        if selected_agv.state in (AGVState.PICKING_UP, AGVState.DROPPING_OFF):
            timer_str = f"  timer={selected_agv.action_timer:.1f}s"
        if selected_agv.is_blocked:
            timer_str += f"  BLOCKED {selected_agv.blocked_timer:.1f}s"
        job_str = ""
        if selected_agv.current_job:
            job_str = f"  job={selected_agv.current_job.job_type.value}"
        lines.append(f"Selected: AGV {sid}  state={st}  pos={pos}  target={tgt}{carrying}{timer_str}{job_str}")
        # Show cart order info if carrying
        if selected_agv.carrying_cart and selected_agv.carrying_cart.order:
            cart = selected_agv.carrying_cart
            order = cart.order
            ns = order.next_station()
            next_str = f"S{ns}" if ns else "all picked"
            lines.append(f"  Cart C{cart.cart_id} Order #{order.order_id}: picks={order.picks}  "
                         f"next={next_str}  timer={cart.process_timer:.1f}s")
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


def draw_metrics_panel(surface, font_sm, font_md, agvs, carts, dispatcher,
                       sim_elapsed, time_scale, paused, auto_spawn,
                       selected_agv=None):
    """Draw the 300px metrics panel on the right side of the window."""
    px = MAP_WIDTH  # panel x origin
    panel_rect = pygame.Rect(px, 0, PANEL_WIDTH, MAP_HEIGHT)
    pygame.draw.rect(surface, PANEL_BG, panel_rect)

    y = 10
    line_h = 16
    section_gap = 8

    def header(text):
        nonlocal y
        pygame.draw.line(surface, PANEL_SEPARATOR, (px + 10, y), (px + PANEL_WIDTH - 10, y))
        y += 4
        txt = font_md.render(text, True, PANEL_HEADER)
        surface.blit(txt, (px + 10, y))
        y += line_h + 4

    def row(label, value, color=PANEL_TEXT):
        nonlocal y
        txt = font_sm.render(f"  {label}: {value}", True, color)
        surface.blit(txt, (px + 8, y))
        y += line_h

    def row_raw(text, color=PANEL_TEXT):
        nonlocal y
        txt = font_sm.render(f"  {text}", True, color)
        surface.blit(txt, (px + 8, y))
        y += line_h

    # ── 1. SIMULATION ──
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

    # ── 2. FLEET STATUS ──
    header("FLEET STATUS")
    agv_list = agvs or []
    idle_count = sum(1 for a in agv_list if a.state == AGVState.IDLE)
    active_count = len(agv_list) - idle_count
    row("AGVs", f"{active_count} active / {idle_count} idle / {len(agv_list)} total")

    cart_list = carts or []
    spawned = sum(1 for c in cart_list if c.state == CartState.SPAWNED)
    in_transit = sum(1 for c in cart_list if c.state in (
        CartState.TO_BOX_DEPOT, CartState.IN_TRANSIT_TO_PICK,
        CartState.IN_TRANSIT_TO_PACKOFF, CartState.IN_TRANSIT))
    processing = sum(1 for c in cart_list if c.state in (
        CartState.AT_BOX_DEPOT, CartState.PICKING, CartState.AT_PACKOFF))
    completed = sum(1 for c in cart_list if c.state == CartState.COMPLETED)
    row("Carts", f"{len(cart_list)} total")
    row_raw(f"Spawned: {spawned}  Transit: {in_transit}")
    row_raw(f"Processing: {processing}  Done: {completed}")
    y += section_gap

    # ── 3. STATION CAPACITY ──
    header("STATION CAPACITY")
    fill = dispatcher._station_fill_cache if dispatcher else {}
    station_order = ["Box_Depot", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "Pack_off"]
    for sid in station_order:
        cur, cap, rate = fill.get(sid, (0, STATIONS.get(sid, 0), 0.0))
        pct = int(rate * 100)
        # Color dot
        if rate <= 0.50:
            dot_color = PANEL_GREEN
        elif rate <= 0.75:
            dot_color = PANEL_YELLOW
        else:
            dot_color = PANEL_RED
        # Draw dot
        dot_y = y + line_h // 2
        pygame.draw.circle(surface, dot_color, (px + 16, dot_y), 4)
        # Label
        display_name = sid.replace("_", " ")
        txt = font_sm.render(f"    {display_name}: {cur}/{cap} ({pct}%)", True, PANEL_TEXT)
        surface.blit(txt, (px + 8, y))
        y += line_h
    y += section_gap

    # ── 4. THROUGHPUT ──
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

    # ── 5. BOTTLENECK ALERTS ──
    header("ALERTS")
    if dispatcher:
        alerts = dispatcher.get_bottleneck_alerts(carts or [])
        if alerts:
            for alert in alerts[:5]:
                row_raw(f"! {alert}", PANEL_RED)
        else:
            row_raw("No alerts", PANEL_GREEN)
    y += section_gap

    # ── 6. SELECTED AGV ──
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

    # ── 7. Controls hint ──
    controls_y = MAP_HEIGHT - 20
    ctrl_txt = font_sm.render("A:AGV C:Cart T:Auto Space:Pause Up/Dn:Speed", True, PANEL_SEPARATOR)
    surface.blit(ctrl_txt, (px + 10, controls_y))


def render(screen, tiles, font_sm, font_md, agvs=None, selected_agv=None,
           time_scale=1.0, carts=None, dispatcher=None,
           sim_elapsed=0.0, paused=False, auto_spawn=False):
    """Full frame render: background → tiles → labels → stationary carts → AGVs → carried carts → panel."""
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

    # Station tile color overlay based on fill rate
    station_fill = dispatcher._station_fill_cache if dispatcher else None
    if station_fill and dispatcher:
        overlay = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        for station_id, (current, capacity, rate) in station_fill.items():
            if not station_id.startswith("S"):
                continue
            if rate <= 0.50:
                ov_color = (30, 200, 30, 40)      # green tint
            elif rate <= 0.75:
                ov_color = (230, 200, 0, 50)       # yellow tint
            else:
                ov_color = (220, 50, 50, 60)        # red tint
            for pos in dispatcher.get_station_tile_positions(station_id):
                overlay.fill(ov_color)
                screen.blit(overlay, (pos[0] * TILE_SIZE, pos[1] * TILE_SIZE))

    draw_labels(screen, font_sm, font_md, station_fill=station_fill)

    # Draw stationary carts (before AGVs so AGVs render on top)
    if carts:
        for cart in carts:
            if cart.carried_by is None:
                draw_cart(screen, cart, font_sm)

    # Draw AGVs
    if agvs:
        for agv in agvs:
            draw_agv(screen, agv, font_md)

    # Draw carried carts (after AGVs so they appear on top)
    if carts:
        for cart in carts:
            if cart.carried_by is not None:
                render_pos = cart.carried_by.get_render_pos()
                draw_cart(screen, cart, font_sm, carried_render_pos=render_pos)

    # Metrics panel (right side)
    draw_metrics_panel(screen, font_sm, font_md, agvs or [], carts or [],
                       dispatcher, sim_elapsed, time_scale, paused, auto_spawn,
                       selected_agv=selected_agv)


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
        path = astar(graph, start, goal, tiles=tiles)
        if path:
            print(f"  {desc}: {len(path)} tiles, "
                  f"~{len(path) * TILE_TRAVEL_TIME:.0f}s")
        else:
            print(f"  {desc}: NO PATH FOUND!")
    print("--- End verification ---\n")


def _reset_id_counters():
    """Reset class-level ID counters so each headless run starts fresh."""
    AGV._next_id = 1
    Cart._next_id = 1
    Order._next_id = 1
    Job._next_id = 1


def run_headless(num_agvs=4, num_carts=8, sim_duration=28800.0, tick_dt=0.1,
                 verbose=False):
    """Run the simulation without pygame rendering, using a fixed timestep.

    Returns a dict of performance metrics.
    """
    _reset_id_counters()
    wall_start = _time.monotonic()

    tiles = build_map()
    graph = build_graph(tiles)
    dispatcher = Dispatcher(tiles)

    sim_elapsed = 0.0
    total_ticks = 0

    # --- Instant pre-placement of all AGVs and carts on valid tiles ---
    placeable = [pos for pos in graph
                 if tiles[pos].tile_type in (TileType.PARKING, TileType.PICK_STATION)]
    random.shuffle(placeable)

    total_entities = num_agvs + num_carts
    if total_entities > len(placeable):
        raise ValueError(
            f"Cannot place {total_entities} entities ({num_agvs} AGVs + "
            f"{num_carts} carts) — only {len(placeable)} PARKING/PICK_STATION "
            f"tiles available in the graph."
        )

    agvs = []
    carts = []
    slot = 0
    for _ in range(num_agvs):
        agvs.append(AGV(placeable[slot]))
        slot += 1
    for _ in range(num_carts):
        carts.append(Cart(placeable[slot]))
        slot += 1

    # Utilization tracking (per-AGV tick counters) — active from tick 0
    idle_ticks = {agv.agv_id: 0 for agv in agvs}
    blocked_ticks = {agv.agv_id: 0 for agv in agvs}
    total_tracked = {agv.agv_id: 0 for agv in agvs}

    # Optionally suppress all print output
    devnull = open(os.devnull, 'w') if not verbose else None
    ctx = contextlib.redirect_stdout(devnull) if devnull else contextlib.nullcontext()

    try:
        with ctx:
            while sim_elapsed < sim_duration:
                # --- Update AGVs ---
                for agv in agvs:
                    agv.update(tick_dt, agvs, carts, graph, tiles)

                # --- Update cart processing timers ---
                for cart in carts:
                    cart.update(tick_dt)

                # --- Dispatcher ---
                dispatcher.update(carts, agvs, graph, tiles, sim_elapsed=sim_elapsed)

                # --- Utilization tracking ---
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

    # --- Compute metrics ---
    completed = dispatcher.completed_orders
    hours = sim_elapsed / 3600.0
    orders_per_hour = completed / hours if hours > 0 else 0.0

    cycle_times = list(dispatcher.cycle_times)
    avg_cycle = sum(cycle_times) / len(cycle_times) if cycle_times else 0.0

    # Utilization: fraction of tracked ticks NOT idle
    total_t = sum(total_tracked.values())
    total_idle = sum(idle_ticks.values())
    total_blocked = sum(blocked_ticks.values())
    agv_utilization = 1.0 - (total_idle / total_t) if total_t > 0 else 0.0
    agv_blocked_fraction = total_blocked / total_t if total_t > 0 else 0.0

    # Station fill snapshot
    station_fill = {}
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
    print("Controls: A=spawn AGV, C=spawn Cart, P=pickup cart, R=return, TAB=cycle, Click=send, D=debug")
    print("          Space=pause, T=auto-spawn, Up/Down=speed steps")
    print("Press Q or close window to quit.")

    verify_graph(graph, tiles)

    dispatcher = Dispatcher(tiles)

    # AGV & cart state
    agvs = []
    carts = []
    selected_agv = None
    time_scale = 1.0        # multiplier for simulation speed
    speed_index = 1         # index into SPEED_STEPS (1.0x)
    paused = False
    auto_spawn = False
    auto_spawn_timer = 0.0
    sim_elapsed = 0.0

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
                    print(f"Speed: {time_scale}x")

                elif event.key == pygame.K_DOWN:
                    speed_index = max(speed_index - 1, 0)
                    time_scale = SPEED_STEPS[speed_index]
                    print(f"Speed: {time_scale}x")

                elif event.key == pygame.K_SPACE:
                    paused = not paused
                    print(f"{'PAUSED' if paused else 'RESUMED'}")

                elif event.key == pygame.K_t:
                    auto_spawn = not auto_spawn
                    auto_spawn_timer = 0.0
                    print(f"Auto-spawn: {'ON' if auto_spawn else 'OFF'}")

                elif event.key == pygame.K_a:
                    # Spawn new AGV at spawn tile
                    if any(a.pos == AGV_SPAWN_TILE for a in agvs):
                        print("Cannot spawn: spawn tile occupied by another AGV!")
                    else:
                        new_agv = AGV(AGV_SPAWN_TILE)
                        agvs.append(new_agv)
                        selected_agv = new_agv
                        print(f"Spawned AGV {new_agv.agv_id} at {AGV_SPAWN_TILE}")

                elif event.key == pygame.K_c:
                    # Spawn cart at first available CART_SPAWN_TILE
                    occupied = {c.pos for c in carts if c.carried_by is None}
                    spawned = False
                    for spawn_pos in CART_SPAWN_TILES:
                        if spawn_pos not in occupied:
                            new_cart = Cart(spawn_pos)
                            carts.append(new_cart)
                            print(f"Spawned Cart C{new_cart.cart_id} at {spawn_pos}")
                            spawned = True
                            break
                    if not spawned:
                        print("All cart spawn tiles occupied!")

                elif event.key == pygame.K_p:
                    # Pickup: selected IDLE AGV (not carrying, no job) → nearest SPAWNED/IDLE cart
                    if selected_agv and selected_agv.current_job:
                        print(f"AGV {selected_agv.agv_id} busy with autonomous job")
                    elif selected_agv and selected_agv.state == AGVState.IDLE and not selected_agv.carrying_cart:
                        # Find nearest cart that is SPAWNED or IDLE
                        best_cart = None
                        best_dist = float('inf')
                        ax, ay = selected_agv.pos
                        for cart in carts:
                            if cart.state in (CartState.SPAWNED, CartState.IDLE) and cart.carried_by is None:
                                dist = abs(cart.pos[0] - ax) + abs(cart.pos[1] - ay)
                                if dist < best_dist:
                                    best_dist = dist
                                    best_cart = cart
                        if best_cart:
                            if selected_agv.pickup_cart(best_cart, graph, tiles):
                                print(f"AGV {selected_agv.agv_id} → pickup C{best_cart.cart_id} "
                                      f"at {best_cart.pos} ({len(selected_agv.path)} tiles)")
                            else:
                                print(f"AGV {selected_agv.agv_id}: no path to C{best_cart.cart_id}!")
                        else:
                            print("No available carts to pick up")
                    elif selected_agv and selected_agv.carrying_cart:
                        print(f"AGV {selected_agv.agv_id} already carrying C{selected_agv.carrying_cart.cart_id}")

                elif event.key == pygame.K_r:
                    # Return selected idle AGV to spawn (blocked while carrying)
                    if selected_agv and selected_agv.state == AGVState.IDLE:
                        if selected_agv.carrying_cart:
                            print(f"AGV {selected_agv.agv_id} carrying cart — drop off first!")
                        elif selected_agv.pos == AGV_SPAWN_TILE:
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

                elif event.key == pygame.K_d:
                    # ── DEBUG DUMP ──
                    print("\n" + "=" * 60)
                    print("DEBUG DUMP")
                    print("=" * 60)

                    # 1) AGV Not Moving?
                    print("\n--- AGV Status ---")
                    if not agvs:
                        print("  (no AGVs spawned)")
                    for agv in agvs:
                        sel = " [SELECTED]" if agv is selected_agv else ""
                        print(f"  AGV {agv.agv_id}{sel}:")
                        print(f"    state:       {agv.state.value}")
                        print(f"    pos:         {agv.pos}")
                        print(f"    path:        {len(agv.path)} tiles"
                              f"{' → ' + str(agv.path[-1]) if agv.path else ''}")
                        print(f"    path_index:  {agv.path_index}  progress: {agv.path_progress:.2f}")
                        print(f"    current_job: {agv.current_job.job_id if agv.current_job else None}"
                              f"  carrying: {'C' + str(agv.carrying_cart.cart_id) if agv.carrying_cart else None}")

                    # 2) Cart Not Getting Order?
                    print("\n--- Cart Status ---")
                    if not carts:
                        print("  (no carts spawned)")
                    for cart in carts:
                        at_depot = any(
                            t.station_id == "Box_Depot"
                            for t in [tiles.get(cart.pos)]
                            if t and t.station_id
                        )
                        print(f"  Cart C{cart.cart_id}:")
                        print(f"    state:         {cart.state.value}")
                        print(f"    pos:           {cart.pos}  at_box_depot: {at_depot}")
                        print(f"    process_timer: {cart.process_timer:.1f}  (BOX_DEPOT_TIME={BOX_DEPOT_TIME})")
                        print(f"    carried_by:    {'AGV ' + str(cart.carried_by.agv_id) if cart.carried_by else None}")
                        print(f"    order:         {cart.order.order_id if cart.order else None}")

                        # 3) Routing — remaining stations & occupancy
                        if cart.order:
                            remaining = [s for s in cart.order.stations_to_visit
                                         if s not in cart.order.completed_stations]
                            print(f"    remaining:     {['S' + str(s) for s in remaining]}")
                            reserved = dispatcher._reserved_tiles(carts)
                            for sid_num in remaining:
                                sid = f"S{sid_num}"
                                key = (sid, TileType.PICK_STATION)
                                all_tiles = dispatcher._station_tiles.get(key, [])
                                occupied = sum(1 for p in all_tiles if p in reserved)
                                cap = len(all_tiles)
                                print(f"      {sid}: {occupied}/{cap} occupied")

                    # 4) Dispatcher jobs summary
                    print(f"\n--- Dispatcher ---")
                    print(f"  pending_jobs:  {len(dispatcher.pending_jobs)}")
                    for j in dispatcher.pending_jobs:
                        print(f"    Job #{j.job_id} {j.job_type.value} C{j.cart.cart_id} → {j.target_pos}")
                    print(f"  active_jobs:   {len(dispatcher.active_jobs)}")
                    for j in dispatcher.active_jobs:
                        agv_id = j.assigned_agv.agv_id if j.assigned_agv else "?"
                        print(f"    Job #{j.job_id} {j.job_type.value} C{j.cart.cart_id} → {j.target_pos} (AGV {agv_id})")
                    print(f"  completed_orders: {dispatcher.completed_orders}")
                    print("=" * 60 + "\n")

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if mx >= MAP_WIDTH:
                    continue  # click in panel area — ignore
                # Left click: set destination for selected idle AGV (skip if busy with job)
                if selected_agv and selected_agv.current_job:
                    print(f"AGV {selected_agv.agv_id} busy with autonomous job")
                elif selected_agv and selected_agv.state == AGVState.IDLE:
                    gx = mx // TILE_SIZE
                    gy = my // TILE_SIZE
                    clicked = (gx, gy)
                    if clicked in tiles:
                        tile = tiles[clicked]
                        if tile.tile_type in (TileType.PICK_STATION, TileType.PARKING):
                            if selected_agv.carrying_cart:
                                # Carrying a cart → dropoff at destination
                                if selected_agv.start_dropoff(clicked, graph, tiles):
                                    print(f"AGV {selected_agv.agv_id} → dropoff C{selected_agv.carrying_cart.cart_id} "
                                          f"at {clicked} ({len(selected_agv.path)} tiles)")
                                else:
                                    print(f"AGV {selected_agv.agv_id}: no path to {clicked}!")
                            else:
                                # Not carrying → normal move
                                if selected_agv.set_destination(clicked, graph, tiles):
                                    print(f"AGV {selected_agv.agv_id} → {clicked} "
                                          f"({tile.tile_type.value}"
                                          f"{' ' + tile.station_id if tile.station_id else ''}, "
                                          f"{len(selected_agv.path)} tiles)")
                                else:
                                    print(f"AGV {selected_agv.agv_id}: no path to {clicked}!")

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
                        print(f"[Auto] Spawned Cart C{new_cart.cart_id} at {spawn_pos}")
                        break

        if not paused:
            # Update all AGVs
            for agv in agvs:
                agv.update(sim_dt, agvs, carts, graph, tiles)

            # Update cart processing timers
            for cart in carts:
                cart.update(sim_dt)

            # Dispatcher orchestrates autonomous cart lifecycle
            dispatcher.update(carts, agvs, graph, tiles, sim_elapsed=sim_elapsed)

        render(screen, tiles, font_sm, font_md, agvs, selected_agv, time_scale, carts,
               dispatcher=dispatcher, sim_elapsed=sim_elapsed, paused=paused,
               auto_spawn=auto_spawn)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
