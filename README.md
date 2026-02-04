# AGV Warehouse Simulation

Discrete-event simulation of an automated warehouse with AGVs (Automated Guided Vehicles) and picking carts. Models the complete cart lifecycle — spawn, load at Box Depot, pick items at stations, unload at Pack-off, recycle — to identify bottlenecks and optimize fleet size and routing.

Built with Python and Pygame. Runs interactively (GUI) or headless (benchmarking).

---

## Quick Start

```bash
# Clone and set up
python -m venv venv
source venv/bin/activate
pip install -e .            # installs pygame dependency

# Run interactive GUI
python -m agv_simulation

# Run tests
pip install -e ".[dev]"
pytest tests/ -v
```

### Controls (GUI mode)

| Key | Action |
|-----|--------|
| `A` | Spawn AGV |
| `C` | Spawn cart |
| `Space` | Pause / resume |
| `T` | Toggle auto-spawn (30s interval) |
| `TAB` | Cycle selected AGV |
| `Up/Down` | Speed (0.5x to 100x) |
| `D` | Debug dump to console |
| `Q` / `ESC` | Quit |
| Left click | Send selected AGV to tile (or drop off cart) |

---

## Project Structure

```
agv_simulation/            # Core package
  __main__.py              # Interactive GUI entry point (Pygame event loop)
  constants.py             # All tunable values: grid size, timings, colors, layout
  enums.py                 # TileType, AGVState, CartState, JobType
  models.py                # Cart, Order, Job, Tile data classes; STATIONS dict
  agv.py                   # AGV entity: movement, pickup/dropoff, collision avoidance
  pathfinding.py           # A* with weighted edges (highway=1, other=10)
  map_builder.py           # build_map() → 60x40 tile grid; build_graph() → directed adjacency
  dispatcher.py            # Job orchestration, capacity-based routing, lifecycle management
  renderer.py              # Pygame drawing: map, entities, metrics panel
  headless.py              # Non-GUI runner for benchmarking (instant-spawn mode)
  pygame_stub.py           # Mock pygame for testing without display

tests/
  conftest.py              # Installs pygame stub before imports
  test_collision_avoidance.py  # 17 tests: pathfinding, routing, collision, lifecycle

sweep.py                   # Parameter sweep CLI (multiprocessing)
pyproject.toml             # Python 3.10+, pygame>=2.0, pytest>=7.0
```

### Documentation

| File | Purpose |
|------|---------|
| `AGV_Warehouse_Simulation_PRD.md` | Full specification (v2.1) — source of truth |
| `AGV_Quick_Reference.md` | Constants, state machines, station capacities |
| `GETTING_STARTED.md` | Setup walkthrough, manual test procedures |
| `Token_Efficient_Prompting.md` | Tips for working with Claude Code on this project |

---

## Architecture

```
__main__.py (GUI)  or  headless.py (benchmark)
       │                      │
       ▼                      ▼
   ┌───────┐  updates   ┌─────────┐
   │  AGVs │◄───────────►│Dispatcher│
   │agv.py │             │          │ creates/assigns jobs, manages lifecycle
   └───┬───┘             └────┬─────┘
       │                      │
       ▼                      ▼
  pathfinding.py         models.py (Cart, Order, Job)
  (A* routing)
       │
       ▼
  map_builder.py ──► 60x40 tile grid + directed graph
```

**Data flow each tick:**
1. AGVs move along A* paths, detect collisions, reroute if blocked
2. Dispatcher checks cart states, creates jobs, assigns idle AGVs
3. Station timers tick down (Box Depot 45s, Pick 90s/item, Pack-off 60s)
4. Renderer draws current state + metrics panel (GUI only)

---

## Key Design Decisions

These invariants are critical — do not break them:

- **Carts never die.** After Pack-off, carts return to Box Depot and get a new order. The cycle repeats forever.
- **Highways are one-way.** The main loop runs anti-clockwise. `build_graph()` enforces directional constraints. Bidirectional S-zones are deferred.
- **A\* prefers highways.** Edge cost: highway tiles = 1, all others = 10. This keeps traffic on designated routes.
- **Capacity-based routing.** Dispatcher picks stations by fill rate: prefer <50% full, then <75%, then any. Ties broken by A* path distance.
- **Collision avoidance, not prevention.** AGVs detect blocked tiles ahead and reroute immediately. 3s block timeout triggers Dispatcher nudging. 2s reroute cooldown prevents thrashing.
- **MAX_CONCURRENT_DISPATCHES = 12.** Limits simultaneous active jobs to prevent highway gridlock.

---

## Running Modes

### Interactive GUI

```bash
python -m agv_simulation
```

Opens a 1500x800 Pygame window (1200px map + 300px metrics panel). Spawn AGVs/carts manually or toggle auto-spawn.

### Headless Benchmarking

```python
from agv_simulation import run_headless

result = run_headless(num_agvs=10, num_carts=20, sim_duration=7200, tick_dt=0.1)
print(f"Throughput: {result['orders_per_hour']} orders/hr")
print(f"Utilization: {result['agv_utilization']*100:.1f}%")
```

All entities are **instant-spawned** on random parking/station tiles at tick 0 (no spawn bottleneck). Returns dict with: `completed_orders`, `orders_per_hour`, `avg_cycle_time`, `agv_utilization`, `agv_blocked_fraction`.

### Parameter Sweep

```bash
python sweep.py                                          # default grid
python sweep.py --agvs 4,8,12 --carts 8,16,24 --duration 3600
python sweep.py --parallel --workers 8 --csv results.csv # parallel execution
```

Outputs a table of throughput metrics across AGV/cart configurations and identifies the best combination.

---

## Testing

```bash
pytest tests/ -v
```

17 tests covering:
- A* highway preference and blocked-tile avoidance
- Directional constraints on highway rows
- AGV collision detection and rerouting
- Spawn guard (no overlap on spawn tiles)
- Station fill tracking and capacity-based routing
- Nearest-AGV job assignment

Tests use `pygame_stub.py` — no display server required.

---

## Map Layout

60 columns x 40 rows. Key positions (defined in `constants.py` and `map_builder.py`):

- **Highways:** Left col 9 (south), right col 38 (north), top row 7 (east), bottom row 38 (west) — anti-clockwise loop
- **AGV spawn:** (1, 7), 8 tiles
- **Cart spawn:** (0, 7)
- **Box Depot:** Capacity 8, near top-left
- **Pack-off:** Capacity 4, near bottom-right
- **Pick stations S1-S9:** Scattered across interior, capacities 3-5 each

---

## Dependencies

| Dependency | Version | Purpose |
|-----------|---------|---------|
| Python | >= 3.10 | Runtime |
| Pygame | >= 2.0 | GUI rendering |
| Pytest | >= 7.0 | Testing (dev) |

No other dependencies. Install with `pip install -e .` (or `pip install -e ".[dev]"` for tests).

---

## For AI Agents

If you are an AI assistant working on this codebase:

1. **Read the PRD first** (`AGV_Warehouse_Simulation_PRD.md`) — it is the single source of truth for all design decisions.
2. **Check `AGV_Quick_Reference.md`** for constants, state machines, and station capacities before making changes.
3. **Run `pytest tests/ -v` after any change** to verify nothing is broken.
4. **Respect the key invariants** listed above (carts never die, highways one-way, etc.).
5. **The dispatcher is the most complex module** (632 lines). Changes there require careful understanding of the job lifecycle. Read it fully before modifying.
6. **Map coordinates are (col, row)** not (x, y) in the traditional sense. Column = x-axis, Row = y-axis. (0,0) is top-left.
7. **Speed multiplier scales all timers.** `actual_dt = real_dt * speed_multiplier`. Don't add separate timer logic.
8. **Headless mode skips rendering entirely.** It shares AGV/Cart/Dispatcher logic with GUI mode but uses instant-spawn placement.
