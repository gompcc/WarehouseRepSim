# AGV Warehouse Simulation - Product Requirements Document (PRD)
**Version 1.0 - Definitive Specification**  
**Last Updated:** January 26, 2026  
**Technology:** Python + Pygame

---

## TABLE OF CONTENTS
1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Map & Layout Specification](#3-map--layout-specification)
4. [Entity Specifications](#4-entity-specifications)
5. [Timing & Performance Constants](#5-timing--performance-constants)
6. [Logic & Behavior Rules](#6-logic--behavior-rules)
7. [User Interface Requirements](#7-user-interface-requirements)
8. [Phase Implementation Plan](#8-phase-implementation-plan)
9. [Testing & Success Criteria](#9-testing--success-criteria)
10. [Future Enhancements](#10-future-enhancements)

---

## 1. PROJECT OVERVIEW

### 1.1 Purpose
Create a discrete-event simulation of an AGV (Automated Guided Vehicle) warehouse system to:
- Visualize cart and AGV movement through the warehouse
- Identify bottlenecks in the current system
- Test optimization scenarios (AGV count, routing logic, capacity changes)
- Measure throughput and utilization metrics

### 1.2 Scope
This simulation models the complete lifecycle of carts from spawning through picking to pack-off, including:
- AGV movement and job assignment
- Cart routing based on order contents
- Station capacity management
- Bottleneck detection and metrics

### 1.3 Success Criteria
The simulation is successful when:
1. ✅ Carts complete full lifecycle: Spawn → Box Depot → Pick Stations → Pack-off → Back to Box Depot
2. ✅ AGVs autonomously pick up, transport, and drop off carts
3. ✅ Station capacity tracking correctly influences routing decisions
4. ✅ Bottlenecks appear at Pack-off and Box Depot (matching real-world observations)
5. ✅ Metrics accurately reflect system performance

---

## 2. SYSTEM ARCHITECTURE

### 2.1 Technology Stack
- **Language:** Python 3.8+
- **Graphics:** Pygame
- **Data Structures:** Classes for entities, dictionaries for map
- **Pathfinding:** A* algorithm with directional constraints

### 2.2 Core Classes

```python
class Position:
    """Represents a tile coordinate"""
    x: int  # tile x-coordinate
    y: int  # tile y-coordinate

class Tile:
    """Represents a single map tile"""
    position: Position
    type: TileType  # HIGHWAY, PARKING, PICK_STATION, etc.
    station_id: Optional[str]  # "S1", "Box_Depot", etc.
    neighbors: List[Position]  # for pathfinding graph

class Order:
    """Represents a picking order"""
    id: int
    picks: List[int]  # [1, 3, 5] = need items from S1, S3, S5
    completed_picks: Set[int]  # tracks which stations are done
    state: OrderState  # IN_PROGRESS, COMPLETED, PACKED_OFF

class Cart:
    """Represents a cart carrying orders"""
    id: int
    order: Optional[Order]  # None if cart is empty
    position: Position
    state: CartState
    dwell_timer: float  # for 30-second pick timing

class AGV:
    """Represents an Automated Guided Vehicle"""
    id: int
    position: Position
    carrying_cart: Optional[Cart]
    current_job: Optional[Job]
    state: AGVState
    path: List[Position]  # current path being followed
    path_progress: float  # for smooth animation

class Station:
    """Represents a pick station, Box Depot, or Pack-off area"""
    id: str
    capacity: int
    current_carts: List[Cart]
    positions: List[Position]  # specific parking spots

class Job:
    """Represents a task for an AGV"""
    id: int
    cart: Cart
    from_position: Position
    to_station_id: str
    assigned_agv: Optional[AGV]
    state: JobState

class Dispatcher:
    """Central controller for job assignment and routing"""
    agvs: List[AGV]
    stations: Dict[str, Station]
    job_queue: List[Job]

class Simulation:
    """Main simulation controller"""
    map: Dict[Position, Tile]
    agvs: List[AGV]
    carts: List[Cart]
    stations: Dict[str, Station]
    dispatcher: Dispatcher
    time_elapsed: float
    metrics: Metrics
```

### 2.3 Enums

```python
class TileType(Enum):
    HIGHWAY = "highway"
    PARKING = "parking"
    PICK_STATION = "pick_station"
    BOX_DEPOT = "box_depot"
    PACKOFF = "packoff"
    AGV_SPAWN = "agv_spawn"
    CART_SPAWN = "cart_spawn"
    RACKING = "racking"
    EMPTY = "empty"

class CartState(Enum):
    EMPTY = "empty"  # No order assigned
    SPAWNED = "spawned"  # Just created, waiting for pickup
    TO_BOX_DEPOT = "to_box_depot"  # Being transported to Box Depot
    AT_BOX_DEPOT = "at_box_depot"  # Receiving order
    IN_TRANSIT_TO_PICK = "in_transit_to_pick"  # Being moved to pick station
    PICKING = "picking"  # At pick station, timer running
    IN_TRANSIT_TO_PACKOFF = "in_transit_to_packoff"  # Being moved to pack-off
    AT_PACKOFF = "at_packoff"  # Being unloaded
    COMPLETED = "completed"  # Order complete, ready to return

class AGVState(Enum):
    IDLE = "idle"  # No job, stationary
    RETURNING_TO_SPAWN = "returning_to_spawn"  # Returning to top-left
    MOVING = "moving"  # Following path
    PICKING_UP = "picking_up"  # Lifting cart
    DROPPING_OFF = "dropping_off"  # Releasing cart

class OrderState(Enum):
    IN_PROGRESS = "in_progress"
    ALL_PICKS_COMPLETE = "all_picks_complete"
    PACKED_OFF = "packed_off"

class JobState(Enum):
    PENDING = "pending"  # Waiting for AGV assignment
    IN_PROGRESS = "in_progress"  # AGV is executing
    COMPLETE = "complete"  # Job done
```

---

## 3. MAP & LAYOUT SPECIFICATION

### 3.1 Tile Configuration
- **Tile Size:** 25 pixels × 25 pixels
- **Grid Dimensions:** Approximately 60 tiles wide × 40 tiles tall
- **Canvas Size:** 1500 pixels × 1000 pixels
- **Coordinate System:** (0, 0) at top-left corner

### 3.2 Station Locations & Capacities

**Pick Stations:**
| Station | Capacity | Location Description |
|---------|----------|---------------------|
| S1 | 5 spots | Top-left, first on circuit |
| S2 | 4 spots | Left side, below S1 |
| S3 | 4 spots | Left side, below S2 |
| S4 | 4 spots | Left side, below S3 |
| S5 | 3 spots | Bottom-right (chemicals area) |
| S6 | 4 spots | Right side, above S5 |
| S7 | 4 spots | Right side, above S6 |
| S8 | 4 spots | Right side, above S7 |
| S9 | 4 spots | Top-right, last before Pack-off |

**Special Stations:**
- **Box Depot:** 8 spots (top-center)
- **Pack-off Conveyor:** 4 spots (top-right)
- **AGV Spawn:** 1 tile (top-left corner)
- **Cart Spawn:** 2 tiles (below AGV spawn, left side)

**Parking Locations:**
- Distributed along highway as shown in reference image
- Light blue squares on the map
- Count exact locations from image during Phase 1 implementation

### 3.3 Highway Network
- **Main Loop:** Unidirectional, clockwise flow
- **Entry/Exit Points:** Each station has designated entry and exit tiles
- **Represented By:** Blue circle tiles in visualization
- **Navigation:** AGVs must follow directional constraints

### 3.4 Color Coding

| Element | Color | Visual Representation |
|---------|-------|----------------------|
| Highway | Light Blue | Filled circles |
| Parking | White | Small squares |
| Pick Stations (S1-S9) | Yellow | Large filled squares |
| Box Depot | Brown | Large filled rectangle |
| Pack-off | Purple | Large filled rectangle |
| AGV Spawn | Dark Gray | Square with "A" label |
| Cart Spawn | Purple | Squares with "C" label |
| Racking | Light Yellow | Background areas |
| Empty Space | Light Gray | Background |
| AGV | Orange | Small square with ID |
| Cart (empty) | White | Small rectangle |
| Cart (with order) | Green | Small rectangle |
| Cart (completed) | Blue | Small rectangle |

### 3.5 Map Data Structure

```python
# Example map entry
map_data = {
    Position(5, 10): Tile(
        position=Position(5, 10),
        type=TileType.HIGHWAY,
        station_id=None,
        neighbors=[Position(6, 10), Position(5, 11)]  # Directional!
    ),
    Position(8, 12): Tile(
        position=Position(8, 12),
        type=TileType.PICK_STATION,
        station_id="S1",
        neighbors=[...]
    )
}
```

**CRITICAL:** Map must be manually recreated from reference image with pixel-perfect accuracy. Each tile type and position must match the provided warehouse layout image.

---

## 4. ENTITY SPECIFICATIONS

### 4.1 AGV (Automated Guided Vehicle)

**Properties:**
```python
id: int  # Unique identifier (1, 2, 3, ...)
position: Position  # Current tile location
carrying_cart: Optional[Cart]  # Reference to cart if carrying one
current_job: Optional[Job]  # Currently assigned job
state: AGVState
path: List[Position]  # Path from current position to target
path_progress: float  # 0.0 to 1.0, for smooth tile-to-tile animation
speed: float  # Tiles per second (derived from timing constants)
pickup_timer: float  # Countdown for pickup animation
dropoff_timer: float  # Countdown for dropoff animation
```

**Behavior Rules:**
1. **Spawning:** Created at top-left AGV spawn tile when user presses 'A'
2. **Movement:** Follows path along highway tiles only (unidirectional)
3. **Job Execution:**
   - Receives job from Dispatcher
   - Computes path to pickup location
   - Travels to pickup location
   - Executes 5-second pickup animation
   - Travels to dropoff location
   - Executes 5-second dropoff animation
   - Reports job complete to Dispatcher
4. **Idle Behavior:** When no job assigned, returns to AGV spawn (top-left)
5. **Collision:** Can pass through other AGVs (no collision detection in Phase 1-6)

**State Transitions:**
```
IDLE → (job assigned) → MOVING → (arrives at pickup) → PICKING_UP →
(pickup complete) → MOVING → (arrives at dropoff) → DROPPING_OFF →
(dropoff complete) → IDLE → RETURNING_TO_SPAWN → (arrives) → IDLE
```

### 4.2 Cart

**Properties:**
```python
id: int  # Unique identifier (1, 2, 3, ...)
order: Optional[Order]  # None if empty, Order object if carrying
position: Position  # Current location
state: CartState
dwell_timer: float  # Seconds at current pick station
dwell_required: float  # Total seconds needed at station (30s × num items)
station_id: Optional[str]  # Current station if parked
```

**Behavior Rules:**
1. **Spawning:** Created at cart spawn tile when user presses 'C' (manual) or auto-spawner triggers
2. **Order Assignment:** Receives random order at Box Depot after 45-second loading time
3. **Picking:**
   - Parked at pick station for 30 seconds per item from that station
   - Timer counts down while at station
   - When timer reaches zero, pick is marked complete
4. **Completion:** After all picks done, cart goes to Pack-off
5. **Recycling:** After Pack-off (60 seconds), cart becomes empty and returns to Box Depot for new order
6. **Attachment:** When being carried by AGV, cart position = AGV position

**State Transitions:**
```
EMPTY → (spawned) → SPAWNED → (AGV picks up) → TO_BOX_DEPOT →
(arrives at Box Depot) → AT_BOX_DEPOT → (45s passes, order assigned) →
(AGV picks up) → IN_TRANSIT_TO_PICK → (arrives at pick station) →
PICKING → (30s × items passes) → (AGV picks up) → IN_TRANSIT_TO_PICK →
... → (all picks done) → IN_TRANSIT_TO_PACKOFF → AT_PACKOFF →
(60s passes) → COMPLETED → (AGV picks up) → TO_BOX_DEPOT → AT_BOX_DEPOT → ...
```

**CRITICAL: Cart Recycling**
Carts are NEVER destroyed. After pack-off is complete:
1. Cart state becomes EMPTY
2. Cart needs to return to Box Depot
3. At Box Depot, cart receives a new order
4. Cycle repeats indefinitely

### 4.3 Order

**Properties:**
```python
id: int
picks: List[int]  # List of station numbers (1-9)
completed_picks: Set[int]  # Which stations have been visited
state: OrderState
creation_time: float  # For metrics
completion_time: Optional[float]  # For metrics
```

**Generation Rules:**
1. **Length:** Uniformly random between 1 and 9 items
2. **Content:** Each item is a random integer from 1 to 9 (represents station number)
3. **Duplicates:** Allowed (e.g., [1, 1, 3] = two items from S1, one from S3)
4. **Picking:** Cart visits each UNIQUE station once, picks all items from that station
5. **Example:**
   - Order: [1, 1, 1, 3, 3, 5]
   - Unique stations needed: {1, 3, 5}
   - Dwell times: S1=90s (3 items), S3=60s (2 items), S5=30s (1 item)

**Important Calculation:**
```python
def get_dwell_time_for_station(order, station_id):
    """Returns seconds cart must dwell at this station"""
    items_from_station = order.picks.count(station_id)
    return items_from_station * 30  # 30 seconds per item
```

### 4.4 Station

**Properties:**
```python
id: str  # "S1", "S2", ..., "Box_Depot", "Pack_off"
capacity: int  # Maximum carts that can be at station
current_carts: List[Cart]  # Carts currently parked here
positions: List[Position]  # Specific tile coordinates for parking
type: str  # "PICK", "BOX_DEPOT", "PACK_OFF"
processing_time: float  # Seconds per cart (Box Depot: 45s, Pack-off: 60s)
```

**Behavior Rules:**
1. **Capacity Tracking:** `fill_rate = len(current_carts) / capacity`
2. **Parking Assignment:** When cart arrives, assign to first available position
3. **Processing:**
   - Box Depot: Cart dwells for 45s, then receives order
   - Pick Stations: Cart dwells for 30s × items, then pick marked complete
   - Pack-off: Cart dwells for 60s, then order marked complete
4. **Full Condition:** If `len(current_carts) >= capacity`, station is full

**Station-Specific Logic:**

**Box Depot:**
- When cart arrives: Start 45-second timer
- After 45 seconds: Generate random order, assign to cart
- Cart is then ready for pickup to first pick station

**Pick Stations (S1-S9):**
- When cart arrives: Calculate dwell time (30s × num items from this station)
- After dwell time: Mark station as picked in order
- Cart is ready for pickup to next station or Pack-off

**Pack-off:**
- When cart arrives: Start 60-second timer
- After 60 seconds: Mark order as packed off, set cart to EMPTY state
- Cart is ready for pickup back to Box Depot

### 4.5 Job

**Properties:**
```python
id: int
job_type: JobType  # PICKUP_TO_BOX_DEPOT, MOVE_TO_PICK, etc.
cart: Cart
from_position: Position
to_station_id: str
assigned_agv: Optional[AGV]
state: JobState
creation_time: float
completion_time: Optional[float]
```

**Job Types:**
1. **PICKUP_TO_BOX_DEPOT:** Get empty cart from spawn zone to Box Depot
2. **MOVE_TO_PICK:** Get cart with order to next pick station
3. **MOVE_TO_PACKOFF:** Get cart with completed picks to Pack-off
4. **RETURN_TO_BOX_DEPOT:** Get empty cart from Pack-off back to Box Depot

---

## 5. TIMING & PERFORMANCE CONSTANTS

### 5.1 Movement & Actions

| Constant | Value | Description |
|----------|-------|-------------|
| `TILE_TRAVEL_TIME` | 10 seconds | Time for AGV to move one tile |
| `PICKUP_TIME` | 5 seconds | Time for AGV to lift cart |
| `DROPOFF_TIME` | 5 seconds | Time for AGV to release cart |
| `PICK_TIME_PER_ITEM` | 30 seconds | Time to pick one item at station |
| `BOX_DEPOT_LOADING_TIME` | 45 seconds | Time to load cart with boxes |
| `PACKOFF_UNLOADING_TIME` | 60 seconds | Time to unload cart at Pack-off |

### 5.2 Spawning

| Constant | Value | Description |
|----------|-------|-------------|
| `AUTO_CART_SPAWN_RATE` | 30 seconds | Time between automatic cart spawns (if enabled) |

### 5.3 Derived Values

```python
AGV_SPEED = 1.0 / TILE_TRAVEL_TIME  # = 0.1 tiles/second
```

### 5.4 Speed Control

**User Controls:**
- Arrow Up: Increase simulation speed multiplier
- Arrow Down: Decrease simulation speed multiplier
- Spacebar: Pause/Resume simulation

**Speed Multipliers:** 0.5x, 1x, 2x, 5x, 10x, 20x

**Implementation:**
```python
actual_delta_time = real_delta_time * speed_multiplier
```

---

## 6. LOGIC & BEHAVIOR RULES

### 6.1 Dispatcher Logic

**Job Creation Rules:**

The Dispatcher creates jobs based on cart lifecycle events:

```python
def handle_cart_state_change(cart, dispatcher):
    if cart.state == CartState.SPAWNED:
        # Cart just spawned, needs to go to Box Depot
        dispatcher.create_job(
            job_type=JobType.PICKUP_TO_BOX_DEPOT,
            cart=cart,
            from_position=cart.position,
            to_station_id="Box_Depot"
        )
    
    elif cart.state == CartState.AT_BOX_DEPOT and cart.order is not None:
        # Cart received order, needs to go to first pick station
        next_station = dispatcher.get_next_station_for_cart(cart)
        dispatcher.create_job(
            job_type=JobType.MOVE_TO_PICK,
            cart=cart,
            from_position=cart.position,
            to_station_id=next_station
        )
    
    elif cart.state == CartState.PICKING and cart.dwell_timer <= 0:
        # Pick complete at this station
        current_station_id = extract_station_number(cart.station_id)
        cart.order.completed_picks.add(current_station_id)
        
        if cart.order.is_complete():
            # All picks done, go to Pack-off
            dispatcher.create_job(
                job_type=JobType.MOVE_TO_PACKOFF,
                cart=cart,
                from_position=cart.position,
                to_station_id="Pack_off"
            )
        else:
            # More picks needed, go to next station
            next_station = dispatcher.get_next_station_for_cart(cart)
            dispatcher.create_job(
                job_type=JobType.MOVE_TO_PICK,
                cart=cart,
                from_position=cart.position,
                to_station_id=next_station
            )
    
    elif cart.state == CartState.COMPLETED:
        # Pack-off done, return to Box Depot for new order
        cart.order = None  # Clear order
        cart.state = CartState.EMPTY
        dispatcher.create_job(
            job_type=JobType.RETURN_TO_BOX_DEPOT,
            cart=cart,
            from_position=cart.position,
            to_station_id="Box_Depot"
        )
```

**Job Assignment Rules:**

Phase 1-4 (MVP): First available AGV gets the job
```python
def assign_jobs(dispatcher):
    free_agvs = [agv for agv in dispatcher.agvs if agv.current_job is None]
    pending_jobs = [job for job in dispatcher.job_queue if job.state == JobState.PENDING]
    
    for job in pending_jobs:
        if free_agvs:
            agv = free_agvs.pop(0)  # Take first available
            job.assigned_agv = agv
            agv.current_job = job
            job.state = JobState.IN_PROGRESS
```

Phase 5+ (with optimization): Nearest AGV gets the job
```python
def assign_jobs_optimized(dispatcher):
    free_agvs = [agv for agv in dispatcher.agvs if agv.current_job is None]
    pending_jobs = [job for job in dispatcher.job_queue if job.state == JobState.PENDING]
    
    for job in pending_jobs:
        if free_agvs:
            # Find nearest AGV
            nearest_agv = min(free_agvs, key=lambda agv: manhattan_distance(agv.position, job.from_position))
            free_agvs.remove(nearest_agv)
            job.assigned_agv = nearest_agv
            nearest_agv.current_job = job
            job.state = JobState.IN_PROGRESS
```

### 6.2 Capacity-Based Routing

**Priority System:**

When determining which station a cart should visit next:

```python
def get_next_station_for_cart(cart, stations):
    """
    Returns the next station ID the cart should visit based on:
    1. Which stations the order still needs
    2. Current fill rates of those stations
    3. Proximity to current location (tie-breaker)
    """
    remaining_stations = cart.order.get_remaining_stations()  # e.g., [1, 3, 5, 7]
    
    # Priority 1: Stations with 0-50% capacity
    priority_1 = []
    for station_num in remaining_stations:
        station = stations[f"S{station_num}"]
        if station.get_fill_rate() < 0.5:
            priority_1.append(station_num)
    
    if priority_1:
        # If multiple, choose closest
        return choose_closest_station(cart.position, priority_1)
    
    # Priority 2: Stations with 50-75% capacity
    priority_2 = []
    for station_num in remaining_stations:
        station = stations[f"S{station_num}"]
        if 0.5 <= station.get_fill_rate() < 0.75:
            priority_2.append(station_num)
    
    if priority_2:
        return choose_closest_station(cart.position, priority_2)
    
    # Priority 3: All remaining stations (75-100% capacity)
    # Must go somewhere, choose closest
    return choose_closest_station(cart.position, remaining_stations)
```

**Tie-Breaking (Closest Station):**
```python
def choose_closest_station(current_position, station_numbers):
    """
    Among stations with same priority, choose the closest one.
    Uses path length along highway, not Euclidean distance.
    """
    min_distance = float('inf')
    best_station = station_numbers[0]
    
    for station_num in station_numbers:
        station = stations[f"S{station_num}"]
        path = compute_path(current_position, station.positions[0])
        path_length = len(path)
        
        if path_length < min_distance:
            min_distance = path_length
            best_station = station_num
    
    return f"S{best_station}"
```

**Dynamic Rerouting:**
- Every time a cart finishes at a station, recalculate next station based on CURRENT capacities
- Do NOT plan entire route at order creation
- This allows system to adapt to changing conditions

### 6.3 Overflow & Bottleneck Handling

**Station Full (100% capacity):**
```python
if target_station.is_full():
    # Cart must circle the track until space opens up
    # Implementation: AGV holds cart and returns to highway, dispatcher re-queues job
    # Job stays in PENDING state until station has space
```

**Pack-off Full:**
```python
if packoff_station.is_full():
    # Cart parks in nearest parking spot on highway
    # Implementation: Find nearest parking tile, move cart there
    # Create new job to move to Pack-off when space available
```

**Box Depot Full:**
```python
if box_depot_station.is_full():
    # New carts wait at spawning zone
    # Implementation: Don't create pickup job until Box Depot has space
```

### 6.4 Pathfinding

**A* Algorithm with Directional Constraints:**

```python
def compute_path(start: Position, goal: Position, map_data) -> List[Position]:
    """
    Returns shortest path from start to goal following highway direction rules.
    
    Rules:
    - Main highway: unidirectional (clockwise)
    - S-zones (Phase 7+): bidirectional
    - Must stay on HIGHWAY or STATION tiles
    """
    # Standard A* implementation
    # Neighbor generation respects tile.neighbors (directional)
    # Heuristic: Manhattan distance
    # Return: List of positions from start to goal
```

**Path Following:**
```python
class AGV:
    def update(self, delta_time):
        if self.state == AGVState.MOVING and self.path:
            # Move along path
            self.path_progress += self.speed * delta_time
            
            if self.path_progress >= 1.0:
                # Reached next tile in path
                self.position = self.path[0]
                self.path.pop(0)
                self.path_progress = 0.0
                
                if not self.path:
                    # Reached destination
                    self.handle_arrival()
```

---

## 7. USER INTERFACE REQUIREMENTS

### 7.1 Main Display

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│                     AGV WAREHOUSE SIMULATION                 │
├─────────────────────────────────┬───────────────────────────┤
│                                 │                           │
│                                 │   METRICS PANEL           │
│          MAP CANVAS             │   ─────────────────       │
│       (1500 x 1000 px)          │                           │
│                                 │   Time: 00:15:23          │
│                                 │   Speed: 2.0x             │
│                                 │                           │
│                                 │   STATIONS:               │
│                                 │   S1: 3/5 (60%)           │
│                                 │   S2: 2/4 (50%)           │
│                                 │   ...                     │
│                                 │                           │
│                                 │   TOTALS:                 │
│                                 │   AGVs: 3                 │
│                                 │   Carts: 12               │
│                                 │                           │
│                                 │   BOTTLENECKS:            │
│                                 │   ⚠ Pack-off: 3 waiting   │
└─────────────────────────────────┴───────────────────────────┘
│   Controls: [C] Spawn Cart  [A] Spawn AGV  [↑↓] Speed       │
│            [Space] Pause/Resume  [Q] Quit                    │
└──────────────────────────────────────────────────────────────┘
```

### 7.2 Map Canvas

**Rendering Requirements:**
1. Draw all tiles with appropriate colors
2. Draw station labels (S1-S9, Box Depot, Pack-off)
3. Draw capacity percentages near each station (e.g., "60%" in red if >75%)
4. Draw AGVs with ID numbers
5. Draw carts with color indicating state (empty=white, active=green, done=blue)
6. Draw path lines for AGVs currently moving (optional, helpful for debugging)

**Visual Hierarchy:**
- Background tiles (lowest layer)
- Racking and labels
- Highways and parking
- Stations
- Carts (when stationary)
- AGVs (highest layer)
- Carts being carried (attach to AGV)

### 7.3 Metrics Panel

**Required Metrics:**

```
TIME ELAPSED: 00:15:23
SIMULATION SPEED: 2.0x
STATUS: ▶ RUNNING

───────────────────────────
FLEET STATUS
───────────────────────────
AGVs Active: 3
AGVs Idle: 1
Total AGVs: 4

Carts in System: 12
- Empty: 2
- Picking: 7
- At Pack-off: 3

───────────────────────────
STATION CAPACITY
───────────────────────────
Box Depot: 5/8 (62%)  🟢
S1: 3/5 (60%)  🟡
S2: 2/4 (50%)  🟡
S3: 1/4 (25%)  🟢
S4: 0/4 (0%)   🟢
S5: 3/3 (100%) 🔴
S6: 2/4 (50%)  🟡
S7: 1/4 (25%)  🟢
S8: 2/4 (50%)  🟡
S9: 3/4 (75%)  🔴
Pack-off: 4/4 (100%) 🔴

───────────────────────────
THROUGHPUT
───────────────────────────
Carts Completed: 23
Avg Cycle Time: 8m 32s
Carts/Hour: 7.2

───────────────────────────
BOTTLENECK ALERTS
───────────────────────────
⚠ Pack-off Queue: 3 carts
⚠ S5 Full: 2 carts waiting
```

**Color Coding:**
- 🟢 Green: 0-50% capacity (good)
- 🟡 Yellow: 50-75% capacity (moderate)
- 🔴 Red: 75-100% capacity (busy/full)

### 7.4 Keyboard Controls

| Key | Action |
|-----|--------|
| `C` | Spawn new cart at cart spawn zone |
| `A` | Spawn new AGV at AGV spawn zone |
| `↑` | Increase simulation speed (0.5x → 1x → 2x → 5x → 10x → 20x) |
| `↓` | Decrease simulation speed |
| `Space` | Pause/Resume simulation |
| `R` | Reset simulation (clear all entities, reset time) |
| `T` | Toggle auto-cart spawning (1 cart per 30 seconds) |
| `Q` | Quit application |

### 7.5 Mouse Controls (Optional)

- Click on cart: Show tooltip with order details
- Click on AGV: Show tooltip with current job
- Click on station: Show detailed capacity and waiting carts

---

## 8. PHASE IMPLEMENTATION PLAN

### PHASE 1: Static Map & Data Structures
**Duration:** 1 day  
**Lines of Code:** ~300-400

**Objectives:**
- Set up Pygame window and event loop
- Create all entity classes with empty/stub methods
- Define tile types and colors
- Manually map warehouse layout from reference image
- Render static map with all tiles colored correctly

**Deliverables:**
- `agv_simulation.py` with basic structure
- Map renders correctly, matching reference image
- Station labels visible
- No movement yet

**Key Tasks:**
1. Set up Pygame boilerplate
2. Define `Position`, `Tile`, `TileType` enum
3. Create `map_data` dictionary by manually transcribing reference image
4. Implement `render_map()` function
5. Draw station labels and capacity placeholders

**Success Test:**
- Visual comparison: Does rendered map match reference image?
- Count tiles: Are there correct number of highway, parking, and station tiles?

---

### PHASE 2: Single AGV Movement
**Duration:** 1 day  
**Lines of Code:** +200

**Objectives:**
- Implement pathfinding (A* algorithm)
- Create AGV entity that can move along paths
- Test manual movement (click-to-move for debugging)
- Smooth tile-to-tile animation

**Deliverables:**
- AGV spawns at top-left when 'A' pressed
- AGV can move along highway following directional constraints
- Smooth animation between tiles (not instant teleportation)

**Key Tasks:**
1. Implement A* pathfinding with directional constraints
2. Create `AGV` class with movement logic
3. Implement path following with `path_progress` for smooth animation
4. Add AGV rendering (orange square with ID)
5. Test: AGV can travel from spawn → Box Depot → S1 → Pack-off

**Success Test:**
- Spawn AGV, manually give it destination
- AGV follows correct path (no backwards movement on highway)
- Movement is smooth (interpolated between tiles)
- AGV respects directional constraints

---

### PHASE 3: Cart Spawning & AGV-Cart Interaction
**Duration:** 1 day  
**Lines of Code:** +200

**Objectives:**
- Implement Cart entity
- AGV can pick up and drop off carts
- Carts visually attach to AGVs during transport
- Manual testing of pickup/dropoff cycle

**Deliverables:**
- Cart spawns at cart spawn zone when 'C' pressed
- AGV can be manually commanded to pick up cart (for testing)
- AGV carries cart to destination
- AGV drops off cart at destination
- Cart remains at destination after dropoff

**Key Tasks:**
1. Create `Cart` class with states
2. Implement pickup animation (5-second timer)
3. Implement dropoff animation (5-second timer)
4. Make cart position follow AGV position when carried
5. Visual: Cart attaches to AGV during transport

**Success Test:**
- Spawn cart at cart spawn zone
- Manually command AGV to pick up cart
- AGV moves to cart, executes 5-second pickup
- AGV carries cart to Box Depot (cart follows AGV)
- AGV executes 5-second dropoff
- Cart remains at Box Depot after AGV leaves

---

### PHASE 4: Order System & Complete Lifecycle
**Duration:** 2 days  
**Lines of Code:** +300

**Objectives:**
- Implement Order generation
- Implement station processing (Box Depot, Pick Stations, Pack-off)
- Implement dwell timers
- Complete autonomous cart lifecycle from spawn to completion and back

**Deliverables:**
- Cart receives random order at Box Depot (45s processing)
- Cart visits required pick stations (30s per item)
- Cart goes to Pack-off (60s processing)
- Cart returns to Box Depot for new order (infinite loop)

**Key Tasks:**
1. Create `Order` class with random generation
2. Implement `Station` class with processing timers
3. Box Depot: 45s → assign random order
4. Pick stations: Calculate dwell time (30s × items), timer countdown
5. Pack-off: 60s → mark order complete, cart becomes empty
6. Cart recycling: Empty cart returns to Box Depot
7. Create simple `Dispatcher` that creates jobs at each lifecycle stage
8. AGV autonomously executes jobs

**Success Test:**
- Spawn single cart (press 'C')
- Spawn single AGV (press 'A')
- Watch complete lifecycle WITHOUT manual intervention:
  1. AGV picks up cart from spawn
  2. AGV takes cart to Box Depot
  3. Cart waits 45s, gets order (e.g., [1, 3, 5])
  4. AGV takes cart to S1, waits 30s × (items from S1)
  5. AGV takes cart to S3, waits 30s × (items from S3)
  6. AGV takes cart to S5, waits 30s × (items from S5)
  7. AGV takes cart to Pack-off, waits 60s
  8. AGV returns empty cart to Box Depot
  9. Cycle repeats with new order

**This is the MVP.** If Phase 4 works, the core simulation is functional.

---

### PHASE 5: Multiple AGVs & Job Queue
**Duration:** 1 day  
**Lines of Code:** +200

**Objectives:**
- Support multiple AGVs (user can spawn with 'A')
- Job queue and assignment logic
- Multiple carts and AGVs working simultaneously

**Deliverables:**
- User can spawn multiple AGVs
- Dispatcher assigns jobs to available AGVs (first-available strategy)
- Multiple carts progress through system simultaneously

**Key Tasks:**
1. Extend Dispatcher to track multiple AGVs
2. Implement job queue (FIFO)
3. Job assignment loop (assign pending jobs to free AGVs)
4. Test with 3 AGVs, 5 carts

**Success Test:**
- Spawn 3 AGVs
- Spawn 5 carts rapidly (or enable auto-spawn)
- All carts complete lifecycle
- No deadlocks or stuck carts
- AGVs share workload

---

### PHASE 6: Capacity-Based Routing
**Duration:** 1 day  
**Lines of Code:** +150

**Objectives:**
- Implement priority-based routing (0-50%, 50-75%, 75%+)
- Station capacity tracking and visualization
- Dynamic rerouting

**Deliverables:**
- Carts route to lower-capacity stations first
- Station fill rates displayed on map
- Color-coded station indicators (green/yellow/red)

**Key Tasks:**
1. Implement `get_next_station_for_cart()` with priority logic
2. Add tie-breaking by proximity
3. Update routing to recalculate at each station completion
4. Visualize station capacities on map

**Success Test:**
- Create scenario: S1 at 80%, S3 at 30%
- Spawn cart needing [1, 3]
- Verify cart goes to S3 first (lower capacity)
- Fill S3, spawn another cart needing [1, 3]
- Verify it goes to S1 (only option left)

---

### PHASE 7: Metrics, UI Controls, and Polish
**Duration:** 1-2 days  
**Lines of Code:** +200

**Objectives:**
- Complete metrics panel
- Speed controls (↑↓ arrows)
- Auto-cart spawning (toggle with 'T')
- Bottleneck detection and alerts

**Deliverables:**
- Full metrics panel as specified in section 7.3
- Speed multiplier control
- Pause/resume functionality
- Auto-spawn toggle
- Visual polish and labels

**Key Tasks:**
1. Create metrics panel UI
2. Implement speed multiplier
3. Implement pause/resume
4. Add auto-spawner with 30-second interval
5. Bottleneck detection logic (queue lengths)
6. Polish: better colors, labels, animations

**Success Test:**
- Run simulation at different speeds (1x, 5x, 10x)
- Pause and resume
- Enable auto-spawn, watch system handle continuous flow
- Metrics update in real-time
- Bottleneck alerts appear when Pack-off gets backed up

---

### PHASE 8 (Optional): Optimization Modes
**Duration:** 1 day  
**Lines of Code:** +100

**Objectives:**
- Add "nearest AGV" job assignment mode
- Compare performance metrics between modes
- Parameter adjustment UI

**Deliverables:**
- Toggle between "first available" and "nearest AGV" assignment
- A/B comparison metrics

---

### PHASE 9 (Optional): Advanced Features
**Duration:** 2-3 days  
**Lines of Code:** +300

**Objectives:**
- Collision detection and queuing
- Battery and charging
- Bidirectional S-zone movement
- Realistic order distributions

---

## 9. TESTING & SUCCESS CRITERIA

### 9.1 Unit Tests (Per Phase)

**Phase 1:**
- ✅ Map dimensions correct (60×40 tiles)
- ✅ All tile types rendered with correct colors
- ✅ Station capacities match specification
- ✅ Highway forms complete loop

**Phase 2:**
- ✅ Path from spawn to any station exists
- ✅ Path respects directional constraints (no backwards movement)
- ✅ AGV moves smoothly between tiles
- ✅ AGV reaches destination

**Phase 3:**
- ✅ Cart spawns at correct location
- ✅ AGV picks up cart (5-second animation)
- ✅ Cart position follows AGV during transport
- ✅ AGV drops off cart at destination
- ✅ Cart remains at destination

**Phase 4 (CRITICAL MVP TESTS):**
- ✅ Cart receives order at Box Depot after 45s
- ✅ Order contains 1-9 random items
- ✅ Cart visits only unique stations needed
- ✅ Dwell time = 30s × (items from station)
- ✅ All picks marked complete
- ✅ Cart goes to Pack-off after all picks
- ✅ Pack-off processing takes 60s
- ✅ Empty cart returns to Box Depot
- ✅ Cart receives new order and repeats

**Phase 5:**
- ✅ Multiple AGVs operate simultaneously without conflicts
- ✅ Jobs assigned fairly to available AGVs
- ✅ No carts get stuck waiting forever

**Phase 6:**
- ✅ Routing prioritizes lower-capacity stations
- ✅ Tie-breaking by proximity works
- ✅ Dynamic rerouting based on current capacities

**Phase 7:**
- ✅ Metrics update in real-time
- ✅ Speed control works (1x, 2x, 5x, 10x)
- ✅ Pause/resume works
- ✅ Auto-spawn creates cart every 30s

### 9.2 Integration Tests

**Full System Test:**
```
Scenario: 3 AGVs, continuous cart spawning
Duration: 30 minutes sim-time
Expected:
- At least 10 carts complete full lifecycle
- Pack-off bottleneck appears (queue builds up)
- Some stations reach 75%+ capacity
- No crashes or deadlocks
```

**Bottleneck Test:**
```
Scenario: Disable Pack-off (set capacity to 0)
Expected:
- Carts complete picks but cannot pack-off
- Carts accumulate in parking spots
- System detects bottleneck
- Alert appears in metrics panel
```

**Capacity Test:**
```
Scenario: Fill S1 to 100%, spawn 3 carts needing S1
Expected:
- Carts wait (circle track or park)
- As S1 opens up, waiting carts are processed
- No crashes
```

### 9.3 Success Criteria Summary

**The simulation is successful when:**

✅ **Functional Completeness:**
1. Carts complete full lifecycle autonomously
2. Multiple AGVs and carts operate simultaneously
3. Capacity-based routing works correctly
4. Bottlenecks appear as expected

✅ **Visual Quality:**
1. Map matches reference image
2. All entities clearly visible
3. Metrics panel readable and informative
4. Animation smooth (no jitter)

✅ **Usability:**
1. Controls intuitive and responsive
2. Speed adjustment works well
3. Can run simulation for extended periods without issues

✅ **Accuracy:**
1. Timings match specification (30s pick, 45s Box Depot, 60s Pack-off)
2. Routing logic matches PRD
3. Bottlenecks appear in same locations as real warehouse

---

## 10. FUTURE ENHANCEMENTS

### 10.1 Phase 8+ Features

**Optimization Testing:**
- Compare "first available" vs "nearest AGV" assignment
- Test different AGV fleet sizes (5, 10, 15, 20)
- Test different cart fleet sizes
- Measure throughput vs cost

**Realistic Behaviors:**
- Collision detection and queuing
- Battery management and charging
- Bidirectional S-zone movement
- Overtaking via parking spots

**Advanced Analytics:**
- Export data to CSV for analysis
- Heatmap of station utilization over time
- AGV utilization charts
- Bottleneck severity over time

**UI Improvements:**
- Click to inspect entities (tooltips)
- Drag-and-drop to manually move carts (debugging)
- Parameter adjustment panel
- Save/load simulation states

### 10.2 Optimization Questions to Answer

1. **What is the optimal AGV fleet size?**
   - Run with 5, 10, 15, 20 AGVs
   - Measure throughput and idle time
   - Find sweet spot (cost vs performance)

2. **What is the Pack-off bottleneck impact?**
   - Baseline: 4 Pack-off stations
   - Test: 6 Pack-off stations
   - Measure throughput improvement
   - Calculate ROI of adding stations

3. **Does "nearest AGV" assignment help?**
   - A/B test: first-available vs nearest
   - Measure average cart cycle time
   - Measure AGV travel distance

4. **What is theoretical maximum throughput?**
   - Unlimited AGVs, unlimited Pack-off
   - Find system limit (probably Box Depot or pick station capacities)

5. **Should high-demand stations have more capacity?**
   - Test: Increase S1 and S5 capacity by 50%
   - Measure impact on overall throughput

---

## 11. VERSION CONTROL STRATEGY

### 11.1 File Structure

```
agv_warehouse_simulation/
├── agv_simulation.py          # Main simulation file (all phases combined)
├── README.md                   # Setup and run instructions
├── AGV_Warehouse_Simulation_PRD.md  # This document
├── requirements.txt            # Python dependencies
└── phases/                     # Backup: one file per phase
    ├── phase1_static_map.py
    ├── phase2_agv_movement.py
    ├── phase3_cart_interaction.py
    ├── phase4_complete_lifecycle.py
    ├── phase5_multiple_agvs.py
    ├── phase6_capacity_routing.py
    └── phase7_metrics_ui.py
```

### 11.2 Development Approach

**Recommended: Single Evolving File**
- Develop in `agv_simulation.py`
- Add comments marking each phase
- After completing each phase, save backup to `phases/phaseN_description.py`
- This keeps the working file coherent while preserving history

**Alternative: Separate Files**
- Develop `phase1_static_map.py`, run and test
- Copy to `phase2_agv_movement.py`, add new features
- Continue copying forward each phase
- Pro: Easy to roll back to previous working state
- Con: Harder to see full context

### 11.3 Comments in Code

**For each major section, include header comments:**

```python
# ============================================================
# PHASE 1: STATIC MAP & DATA STRUCTURES
# ============================================================

# ----- Constants -----
TILE_SIZE = 25
SCREEN_WIDTH = 1500
SCREEN_HEIGHT = 1000

# ----- Enums -----
class TileType(Enum):
    """Types of tiles in the warehouse map"""
    HIGHWAY = "highway"      # Blue circles - main transport route
    PARKING = "parking"      # White squares - temporary storage
    # ... etc

# ----- Entity Classes -----
class Position:
    """
    Represents a tile coordinate in the warehouse grid.
    (0, 0) is top-left corner.
    """
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y
```

**For complex algorithms, explain the logic:**

```python
def get_next_station_for_cart(cart, stations):
    """
    Determines which station the cart should visit next based on:
    1. Order requirements (which stations still needed)
    2. Station fill rates (prioritize less busy stations)
    3. Proximity (tie-breaker)
    
    Priority system:
    - Priority 1 (0-50% full): Go here first
    - Priority 2 (50-75% full): Go here if no Priority 1 available
    - Priority 3 (75-100% full): Only if no other option
    
    Returns: station_id (e.g., "S3")
    """
    # Implementation...
```

---

## 12. CLAUDE CODE USAGE STRATEGY

### 12.1 Prompt Structure for Each Phase

**Template:**
```
I'm building an AGV warehouse simulation in Python/Pygame. I've completed Phase [N-1] 
and now need to implement Phase [N]: [Phase Name].

CONTEXT:
[Briefly describe what's already working]

CURRENT CODE:
[Paste current agv_simulation.py file if under 400 lines, otherwise just key sections]

PHASE [N] REQUIREMENTS:
[Copy relevant sections from this PRD]

SPECIFIC TASKS:
1. [Task 1]
2. [Task 2]
3. [Task 3]

Please provide:
1. Updated code with Phase [N] features added
2. Comments explaining new sections
3. Test instructions to verify it works

Note: I'm a beginner coder, so please include explanatory comments.
```

### 12.2 Keeping Claude Code on Track

**Include in every prompt:**
- Link back to this PRD: "Reference AGV_Warehouse_Simulation_PRD.md for full specification"
- Emphasize current phase: "We are implementing Phase X. Do not add features from future phases."
- State constraints: "Tile size is 25px. Map must match reference image exactly."

**If Claude Code suggests changes to the PRD:**
- Evaluate if the suggestion improves the design
- If yes, update this PRD before proceeding
- If no, remind Claude Code to follow the PRD as written

### 12.3 Debugging Strategy

**If something doesn't work:**
1. Identify the specific issue (e.g., "AGV doesn't stop at destination")
2. Check PRD: Is the specification clear?
3. Prompt Claude Code: "The AGV doesn't stop at destination. According to the PRD, it should [expected behavior]. Here's the relevant code: [paste]. Please fix."

**If you get stuck:**
- Simplify: Can you test the feature in isolation?
- Add debug prints: Add print statements to track state changes
- Visual debug: Draw extra info on screen (e.g., AGV's target position)

---

## 13. FINAL NOTES

### 13.1 Critical Rules (Never Violate)

1. **Cart Recycling:** Carts are NEVER destroyed. After Pack-off, they return to Box Depot for a new order.

2. **Unique Station Visits:** If an order has [1, 1, 3], the cart visits S1 ONCE (picks both items) and S3 ONCE.

3. **Dwell Time Calculation:** 
   ```python
   dwell_time = order.picks.count(station_id) * 30  # seconds
   ```

4. **Highway Direction:** Main highway is unidirectional (clockwise). AGVs cannot go backwards.

5. **Job Commitment:** Once an AGV is assigned a job, it completes it. No dynamic reassignment (until Phase 8+).

6. **Capacity-Based Routing:** Always recalculate next station based on CURRENT capacities, not initial state.

7. **Spawning Locations:**
   - AGVs spawn at top-left corner
   - Carts spawn at purple cart spawn tiles (below AGV spawn)

8. **Timing Constants:** These are FIXED (unless you're testing optimization scenarios):
   - Tile travel: 10 seconds
   - Pickup: 5 seconds
   - Dropoff: 5 seconds
   - Pick per item: 30 seconds
   - Box Depot: 45 seconds
   - Pack-off: 60 seconds

### 13.2 When to Update This PRD

Update this document if:
- You discover an ambiguity during implementation
- You decide to change a specification (e.g., different timing constant)
- You add a new feature not originally planned
- You simplify a complex feature

**Keep this PRD as the single source of truth.**

### 13.3 Getting Started

**First Steps:**
1. Set up Python environment with Pygame
2. Create project directory structure
3. Start with Phase 1 prompt to Claude Code
4. Reference this PRD in every prompt
5. Build iteratively, testing after each phase

**Initial Prompt for Claude Code:**
```
I'm starting a new AGV warehouse simulation project in Python/Pygame.

PROJECT OVERVIEW:
I'm simulating an automated warehouse with AGVs (vehicles) that move carts through 
a picking circuit. Carts receive orders, visit pick stations, and get packed off.

PHASE 1 GOAL:
Create the static map display matching the warehouse layout in the reference image.

REQUIREMENTS:
- Pygame window: 1500x1000 pixels
- Tile size: 25x25 pixels
- Map should have ~60x40 tiles
- Tile types: HIGHWAY (light blue circles), PARKING (white squares), 
  PICK_STATION (yellow squares), BOX_DEPOT (brown), PACK_OFF (purple),
  AGV_SPAWN (gray), CART_SPAWN (purple), RACKING (light yellow)

STATIONS:
- S1-S9: Pick stations with specific capacities
- Box Depot: 8 spots (top center)
- Pack-off: 4 spots (top right)
- [Full details in attached PRD]

DELIVERABLES:
1. Basic Pygame setup with event loop
2. Tile and Position classes
3. Map data structure (manually transcribe from reference image)
4. Render function to draw all tiles
5. Station labels on map

REFERENCE: I have a detailed PRD document (AGV_Warehouse_Simulation_PRD.md) that 
specifies everything. I'll provide it for context, but for now, just focus on 
Phase 1: rendering the static map.

Please provide:
1. Complete phase1_static_map.py code
2. Comments explaining each section (I'm a beginner)
3. Instructions to run it

[Attach this PRD and the reference image]
```

---

## DOCUMENT VERSION HISTORY

**Version 1.0** - January 26, 2026
- Initial comprehensive PRD based on requirement clarification
- All ambiguities resolved
- Phasing strategy defined
- Ready for implementation

---

**END OF PRODUCT REQUIREMENTS DOCUMENT**

This PRD should serve as the definitive reference throughout development. Any questions or uncertainties should be resolved by updating this document, not by making assumptions during implementation.

Good luck with your simulation! 🚀