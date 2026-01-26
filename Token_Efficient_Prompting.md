# Token-Efficient Prompting Strategy for Claude Code

## Problem
The full PRD is ~20,000 tokens. Pasting it with every prompt would:
- Waste tokens
- Slow down responses
- Cost more
- Fill up Claude Code's context window

## Solution: Layered Information Strategy

### Layer 1: Quick Reference (Primary - Use 90% of the time)
The Quick Reference is only ~2,000 tokens and contains:
- All critical constants
- Station capacities
- Color schemes
- State machines
- Common pitfalls

**Use this for most prompts.**

### Layer 2: Phase-Specific Excerpts (When needed)
Extract only the relevant PRD section for your current phase.
See templates below.

### Layer 3: Full PRD (Rarely)
Only reference when:
- Starting a new phase for the first time
- Resolving major architectural questions
- Claude Code seems confused about overall system

---

## PHASE-SPECIFIC PROMPT TEMPLATES

### PHASE 1: Static Map

**Token count: ~1,500**

```
I'm building an AGV warehouse simulation in Python/Pygame.

PHASE 1 GOAL: Render static warehouse map

SETUP:
- Window: 1500x1000px
- Tiles: 25x25px (~60x40 grid)
- Pygame event loop

TILE TYPES & COLORS:
HIGHWAY: (173,216,230) light blue circles
PARKING: (255,255,255) white squares  
PICK_STATION: (255,255,0) yellow squares
BOX_DEPOT: (139,90,43) brown rectangle
PACK_OFF: (147,112,219) purple rectangle
AGV_SPAWN: (128,128,128) gray square
CART_SPAWN: (147,112,219) purple squares
RACKING: (255,255,224) light yellow

STATIONS:
S1: 5 spots (top-left) | S2-S4: 4 spots each | S5: 3 spots (bottom-right)
S6-S9: 4 spots each | Box_Depot: 8 spots | Pack_off: 4 spots

CLASSES NEEDED:
Position(x, y)
TileType enum
Tile(position, type, station_id, neighbors)

DELIVERABLE:
Complete phase1.py with map rendering and station labels.

I'm a beginner - please add explanatory comments.
```

---

### PHASE 2: AGV Movement

**Token count: ~1,200**

```
PHASE 2: Single AGV movement

CONTEXT: Phase 1 complete - static map renders correctly.

NEW FEATURES:
1. A* pathfinding (with directional constraints)
2. AGV class with movement
3. Smooth tile-to-tile animation
4. Spawn AGV with 'A' key

CONSTANTS:
TILE_TRAVEL_TIME = 10 seconds
AGV_SPEED = 0.1 tiles/second

AGV CLASS:
- id, position, state, path, path_progress
- States: IDLE, MOVING, RETURNING_TO_SPAWN
- update(delta_time): move along path

PATHFINDING:
- Main highway: unidirectional (clockwise)
- A* algorithm
- Use tile.neighbors for directional constraints

TEST:
Spawn AGV, manually set destination, verify:
- Follows correct path (no backwards on highway)
- Smooth animation
- Reaches destination

DELIVERABLE:
Add AGV class and pathfinding to existing code.
```

---

### PHASE 3: Cart Interaction

**Token count: ~1,000**

```
PHASE 3: Cart spawning and AGV-cart interaction

CONTEXT: Phase 2 complete - AGV moves smoothly.

NEW FEATURES:
1. Cart class
2. Pickup/dropoff with timers
3. Cart follows AGV when carried
4. Spawn cart with 'C' key

CONSTANTS:
PICKUP_TIME = 5 seconds
DROPOFF_TIME = 5 seconds

CART CLASS:
- id, order, position, state, dwell_timer
- States: EMPTY, SPAWNED, TO_BOX_DEPOT, AT_BOX_DEPOT, etc.
- Render: white=empty, green=active, blue=completed

PICKUP/DROPOFF:
- AGV.state = PICKING_UP (5s timer)
- Cart.position = AGV.position while carried
- AGV.state = DROPPING_OFF (5s timer)
- Cart stays at dropoff location

TEST:
Spawn AGV + Cart, manually trigger:
- Pickup (5s animation)
- Transport (cart follows AGV)
- Dropoff (5s animation)
- Cart remains at destination

DELIVERABLE:
Add Cart class and pickup/dropoff logic.
```

---

### PHASE 4: Complete Lifecycle (MVP)

**Token count: ~1,800**

```
PHASE 4: Complete cart lifecycle - THE MVP

CONTEXT: Phase 3 complete - AGV can carry carts.

NEW FEATURES:
1. Order generation
2. Station processing (Box Depot, Pick Stations, Pack-off)
3. Dispatcher with job creation
4. Autonomous cart lifecycle

CRITICAL CONSTANTS:
BOX_DEPOT_TIME = 45 seconds
PICK_TIME_PER_ITEM = 30 seconds
PACKOFF_TIME = 60 seconds

ORDER:
- Random 1-9 items (each item 1-9)
- Example: [1,1,3,5] = visit S1(60s), S3(30s), S5(30s)
- CRITICAL: Visit each unique station once

STATION PROCESSING:
Box_Depot: 45s → generate random order
Pick_Station: 30s × (items from station) → mark complete
Pack_off: 60s → mark packed, cart becomes EMPTY

CART LIFECYCLE (CRITICAL):
Spawn → Box_Depot → Pick_Stations → Pack_off → Box_Depot → (repeat)
           ↑________________________________________________|
           CART RECYCLING - gets new order, never destroyed

DISPATCHER:
- Create jobs at lifecycle events
- Assign jobs to free AGVs (first available)
- Job types: PICKUP_TO_BOX_DEPOT, MOVE_TO_PICK, MOVE_TO_PACKOFF, RETURN_TO_BOX_DEPOT

TEST (MVP SUCCESS):
Spawn 1 AGV + 1 Cart, watch full autonomous cycle:
1. AGV picks up cart from spawn
2. Takes to Box Depot (45s)
3. Takes to required stations (30s per item each)
4. Takes to Pack-off (60s)
5. Returns empty cart to Box Depot
6. Cycle repeats with new order

DELIVERABLE:
Add Order, Station, Dispatcher classes. Complete autonomous lifecycle.
```

---

### PHASE 5: Multiple AGVs

**Token count: ~800**

```
PHASE 5: Multiple AGVs and job queue

CONTEXT: Phase 4 complete - single cart completes lifecycle.

NEW FEATURES:
1. Multiple AGV support (spawn with 'A')
2. Job queue (FIFO)
3. Job assignment logic

JOB ASSIGNMENT (Phase 5):
- First available AGV gets job (not nearest)
- Once assigned, AGV completes job (no reassignment)

DISPATCHER UPDATES:
- Track multiple AGVs
- Maintain job_queue (pending, in_progress, complete)
- assign_jobs(): match free AGVs to pending jobs

TEST:
Spawn 3 AGVs + 5 carts:
- All carts complete lifecycle
- No deadlocks
- Jobs distributed among AGVs

DELIVERABLE:
Extend Dispatcher for multiple AGVs.
```

---

### PHASE 6: Capacity-Based Routing

**Token count: ~1,200**

```
PHASE 6: Smart routing based on station capacity

CONTEXT: Phase 5 complete - multiple AGVs working.

NEW FEATURES:
1. Capacity tracking per station
2. Fill rate calculation
3. Priority-based routing

ROUTING PRIORITY:
- 0-50% capacity: Priority 1 (go here first)
- 50-75% capacity: Priority 2 (go if no P1)
- 75-100% capacity: Priority 3 (avoid, last resort)
- Tie-breaker: Choose closest station (by path length)

DYNAMIC REROUTING:
When cart finishes at station, recalculate next station based on CURRENT capacities.

STATION CLASS:
- get_fill_rate(): len(current_carts) / capacity
- has_space(): bool
- Color coding: green <50%, yellow 50-75%, red 75%+

DISPATCHER UPDATE:
def get_next_station_for_cart(cart, stations):
    remaining = cart.order.get_remaining_stations()
    
    # Priority 1: Find 0-50% stations
    priority_1 = [s for s in remaining if fill_rate(s) < 0.5]
    if priority_1: return closest(priority_1)
    
    # Priority 2: Find 50-75% stations
    priority_2 = [s for s in remaining if 0.5 <= fill_rate(s) < 0.75]
    if priority_2: return closest(priority_2)
    
    # Priority 3: Go to closest remaining
    return closest(remaining)

VISUALIZATION:
- Show fill % near each station
- Color-code stations (green/yellow/red)

TEST:
Fill S1 to 80%, S3 to 30%
Spawn cart needing [1,3]
Verify: Goes to S3 first (lower capacity)

DELIVERABLE:
Add capacity tracking and priority routing.
```

---

### PHASE 7: Metrics & UI

**Token count: ~1,000**

```
PHASE 7: Metrics panel and controls

CONTEXT: Phase 6 complete - smart routing works.

NEW FEATURES:
1. Metrics panel (side panel)
2. Speed controls (↑↓ arrows)
3. Pause/resume (Space)
4. Auto-spawn toggle ('T')
5. Bottleneck detection

METRICS TO DISPLAY:
- Time elapsed, speed multiplier, status
- AGV count (active/idle/total)
- Cart count (empty/picking/packoff)
- Station capacities with color coding
- Throughput (carts completed, avg cycle time)
- Bottleneck alerts (Pack-off queue, full stations)

SPEED CONTROL:
- Multipliers: 0.5x, 1x, 2x, 5x, 10x, 20x
- actual_delta = real_delta × multiplier
- Arrow Up: increase, Arrow Down: decrease

AUTO-SPAWN:
- Toggle with 'T' key
- Spawn 1 cart every 30 seconds

BOTTLENECK DETECTION:
if len(packoff_queue) > 3:
    alert("⚠ Pack-off Queue: X carts waiting")

LAYOUT:
Map on left (1500px wide)
Panel on right (300px wide)

DELIVERABLE:
Add metrics panel, speed controls, auto-spawn.
```

---

## GENERAL DEBUGGING PROMPT

**Token count: ~500**

When something breaks:

```
DEBUGGING ISSUE: [Specific problem, e.g., "AGV doesn't stop at destination"]

EXPECTED BEHAVIOR (from PRD):
[What should happen]

CURRENT BEHAVIOR:
[What's actually happening]

RELEVANT CODE:
[Paste the specific function/class having issues - not entire file]

CONSTANTS CHECK:
TILE_TRAVEL_TIME = 10s
PICKUP_TIME = 5s
[etc., only what's relevant]

REQUEST:
Please identify the bug and provide a fix with explanation.
```

---

## TOKEN USAGE COMPARISON

| Approach | Tokens per Prompt |
|----------|------------------|
| Full PRD every time | ~20,000 |
| Phase-specific template | ~800-1,800 |
| Quick Reference | ~2,000 |
| Debug template | ~500 |

**Savings: 90-95% reduction in tokens!**

---

## RECOMMENDED WORKFLOW

### Starting a new phase:
1. Read full PRD section for that phase (yourself)
2. Use phase-specific template above
3. Attach Quick Reference if needed for constants

### Debugging or adding features:
1. Use Quick Reference for constants/rules
2. Paste only relevant code sections
3. Be specific about the issue

### Major architectural questions:
1. Reference specific PRD section: "See AGV_Warehouse_Simulation_PRD.md, Section 6.2"
2. Paste that section only (not entire document)

---

## EXAMPLE EFFICIENT PROMPT (Phase 4)

```
I'm implementing Phase 4 of my AGV warehouse simulation.

GOAL: Complete cart lifecycle (MVP)

WORKING: AGV can pick up and drop off carts

NEED: 
1. Order generation (1-9 random items from stations 1-9)
2. Station processing with timers
3. Dispatcher job creation
4. Cart recycling (returns to Box Depot after Pack-off)

KEY CONSTANTS:
BOX_DEPOT_TIME = 45s
PICK_TIME_PER_ITEM = 30s  ← CRITICAL: If order=[1,1,3], S1 dwell=60s, S3 dwell=30s
PACKOFF_TIME = 60s

CRITICAL RULE - CART RECYCLING:
After Pack-off → cart.state = EMPTY → return to Box Depot → get new order → repeat

CRITICAL RULE - UNIQUE STATION VISITS:
Order [1,1,1,3] → visit S1 ONCE (picks 3 items in 90s), visit S3 ONCE (30s)

CURRENT CODE:
[Paste Cart and AGV classes only]

REQUEST:
1. Add Order class with random generation
2. Add Station class with processing timers
3. Add simple Dispatcher with job creation
4. Test: 1 AGV + 1 cart completes full cycle

I'm a beginner coder - comments appreciated.
```

**Token count: ~800 instead of 20,000!**

---

## KEY TAKEAWAY

✅ **Use phase-specific templates above** - they contain exactly what Claude Code needs
✅ **Reference Quick Reference** - for constants and common patterns  
❌ **Don't paste full PRD** - unless truly needed
❌ **Don't paste entire codebase** - only relevant sections

This approach should save you 90%+ on tokens while keeping Claude Code well-informed!
