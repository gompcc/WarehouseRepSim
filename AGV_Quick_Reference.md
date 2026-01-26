# AGV Warehouse Simulation - Quick Reference
**Companion to the full PRD - Use for quick lookups during development**

## Core Constants (Never Change Without PRD Update)

```python
# Timing (all in seconds)
TILE_TRAVEL_TIME = 10        # AGV movement per tile
PICKUP_TIME = 5              # AGV picking up cart
DROPOFF_TIME = 5             # AGV dropping off cart
PICK_TIME_PER_ITEM = 30      # Picking one item at station
BOX_DEPOT_TIME = 45          # Loading cart with order
PACKOFF_TIME = 60            # Unloading cart at pack-off
AUTO_SPAWN_INTERVAL = 30     # Auto-spawn new cart

# Display
TILE_SIZE = 25               # pixels per tile
SCREEN_WIDTH = 1500
SCREEN_HEIGHT = 1000
```

## Station Capacities

```python
STATION_CAPACITIES = {
    "S1": 5,
    "S2": 4,
    "S3": 4,
    "S4": 4,
    "S5": 3,
    "S6": 4,
    "S7": 4,
    "S8": 4,
    "S9": 4,
    "Box_Depot": 8,
    "Pack_off": 4
}
```

## Keyboard Controls

```python
'C' → Spawn cart
'A' → Spawn AGV
'↑' → Speed up
'↓' → Speed down
Space → Pause/Resume
'T' → Toggle auto-spawn
'R' → Reset
'Q' → Quit
```

## Color Scheme

```python
COLORS = {
    'highway': (173, 216, 230),      # Light blue
    'parking': (255, 255, 255),      # White
    'pick_station': (255, 255, 0),   # Yellow
    'box_depot': (139, 90, 43),      # Brown
    'packoff': (147, 112, 219),      # Purple
    'agv_spawn': (128, 128, 128),    # Gray
    'cart_spawn': (147, 112, 219),   # Purple
    'racking': (255, 255, 224),      # Light yellow
    'agv': (255, 165, 0),            # Orange
    'cart_empty': (255, 255, 255),   # White
    'cart_active': (0, 255, 0),      # Green
    'cart_done': (0, 0, 255),        # Blue
}
```

## Critical Rules

### 1. Cart Lifecycle (NEVER FORGET)
```
Spawn → Box Depot → Pick Stations → Pack-off → Box Depot → ...
         ↑___________________________________________|
         (Cart recycling - gets new order)
```

### 2. Dwell Time Calculation
```python
# If order is [1, 1, 3], cart visits S1 once for 60s, S3 once for 30s
items_from_station = order.picks.count(station_id)
dwell_time = items_from_station * 30  # seconds
```

### 3. Capacity-Based Routing Priority
```python
if fill_rate < 0.5:    # Priority 1 - go here first
if 0.5 <= fill_rate < 0.75:  # Priority 2 - go if no P1
if fill_rate >= 0.75:  # Priority 3 - avoid, only if necessary
# Tie-breaker: closest station (by path length)
```

### 4. Highway Direction
- Main highway: **UNIDIRECTIONAL** (clockwise only)
- S-zones (Phase 7+): Bidirectional
- AGVs cannot reverse on main highway

### 5. Job Assignment (Phase 1-6)
```python
# First available AGV gets the job (not necessarily closest)
free_agvs = [agv for agv in agvs if agv.current_job is None]
if free_agvs:
    agv = free_agvs[0]  # Take first one
```

## Order Generation

```python
# Random order with 1-9 items
length = random.randint(1, 9)
picks = [random.randint(1, 9) for _ in range(length)]
# Example: [1, 1, 3, 5, 7, 7, 7] → visit S1(2 items), S3(1), S5(1), S7(3)
```

## State Machines

### AGV States
```
IDLE → MOVING → PICKING_UP → MOVING → DROPPING_OFF → IDLE
   ↓                                                    ↑
   └─→ RETURNING_TO_SPAWN → (arrives) ─────────────────┘
```

### Cart States
```
EMPTY → SPAWNED → TO_BOX_DEPOT → AT_BOX_DEPOT → 
IN_TRANSIT_TO_PICK → PICKING → IN_TRANSIT_TO_PICK → ... →
IN_TRANSIT_TO_PACKOFF → AT_PACKOFF → COMPLETED → TO_BOX_DEPOT → AT_BOX_DEPOT → ...
```

## Overflow Handling

```python
# Station Full (100% capacity)
if target_station.is_full():
    # Cart circles track until space available
    # Keep job in PENDING queue
    
# Pack-off Full
if packoff.is_full():
    # Park cart in nearest parking spot
    # Create new job when Pack-off opens
    
# Box Depot Full
if box_depot.is_full():
    # New carts wait at spawn zone
    # Don't create pickup job yet
```

## Phase Checklist

### Phase 1: Static Map ✓
- [ ] Map renders correctly
- [ ] All station labels visible
- [ ] Matches reference image

### Phase 2: AGV Movement ✓
- [ ] A* pathfinding works
- [ ] AGV follows highway direction
- [ ] Smooth tile-to-tile animation

### Phase 3: Cart Interaction ✓
- [ ] Cart spawns with 'C'
- [ ] AGV picks up cart (5s animation)
- [ ] Cart follows AGV during transport
- [ ] AGV drops off cart (5s animation)

### Phase 4: Complete Lifecycle ✓ (MVP)
- [ ] Cart gets order at Box Depot (45s)
- [ ] Cart visits required stations
- [ ] Dwell time = 30s × items
- [ ] Cart goes to Pack-off (60s)
- [ ] Cart returns to Box Depot
- [ ] Cycle repeats autonomously

### Phase 5: Multiple AGVs ✓
- [ ] Multiple AGVs spawn with 'A'
- [ ] Jobs distributed among AGVs
- [ ] No conflicts or deadlocks

### Phase 6: Capacity Routing ✓
- [ ] Priority logic works (0-50%, 50-75%, 75%+)
- [ ] Tie-breaking by proximity
- [ ] Dynamic rerouting

### Phase 7: Metrics & UI ✓
- [ ] Metrics panel complete
- [ ] Speed controls (↑↓)
- [ ] Pause/resume (Space)
- [ ] Auto-spawn toggle ('T')

## Common Pitfalls

### ❌ Don't Forget:
1. Cart recycling (never destroy carts!)
2. Visit each unique station once (not per item)
3. Recalculate routing at each station (dynamic)
4. Highway is unidirectional (no backwards)
5. AGV returns to spawn when idle

### ✅ Remember:
1. All times in seconds (not milliseconds)
2. Dwell time per station = items × 30s
3. Orders can have duplicate numbers [1,1,3]
4. Carts go back to Box Depot after Pack-off
5. Speed multiplier affects all timers

## Debugging Tips

### AGV Not Moving?
```python
# Check:
print(f"AGV state: {agv.state}")
print(f"AGV path: {agv.path}")
print(f"AGV current_job: {agv.current_job}")
```

### Cart Not Getting Order?
```python
# Check:
print(f"Cart at Box Depot? {cart.station_id == 'Box_Depot'}")
print(f"Dwell timer: {cart.dwell_timer}")
print(f"Required: {BOX_DEPOT_TIME}")
```

### Routing Not Working?
```python
# Check:
remaining = cart.order.get_remaining_stations()
print(f"Remaining stations: {remaining}")
for sid in remaining:
    station = stations[f"S{sid}"]
    print(f"S{sid} fill rate: {station.get_fill_rate()}")
```

## Test Scenarios

### Basic Test
```
1. Spawn 1 AGV (press 'A')
2. Spawn 1 cart (press 'C')
3. Watch full lifecycle complete
4. Verify cart returns to Box Depot
```

### Capacity Test
```
1. Spawn 5 carts rapidly (all need S1)
2. Watch S1 reach 100%
3. Verify later carts route around S1
4. Watch carts get processed as S1 opens
```

### Bottleneck Test
```
1. Enable auto-spawn ('T')
2. Spawn 3 AGVs
3. Run for 10 sim-minutes
4. Observe Pack-off bottleneck
5. Check metrics for alerts
```

## File Structure

```
agv_simulation.py          # Main file (all phases)
AGV_Warehouse_Simulation_PRD.md  # Full specification
quick_reference.md         # This file
README.md                  # Setup instructions
requirements.txt           # pygame
phases/                    # Backups
  phase1_static_map.py
  phase2_agv_movement.py
  ...
```

## Getting Help

If stuck, check:
1. This quick reference
2. Full PRD (section on your current phase)
3. Reference image (for map layout)
4. Print debug info (state, positions, timers)
5. Claude Code with specific error

---

**Keep this file open while coding!**