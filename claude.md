### 1. Plan Node Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)  
- If something goes sideways, STOP and re-plan immediately - don't keep pushing  
- Use plan mode for verification steps, not just building  
- Write detailed specs upfront to reduce ambiguity  

---

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean  
- Offload research, exploration, and parallel analysis to subagents  
- For complex problems, throw more compute at it via subagents  
- One task per subagent for focused execution  

---

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern  
- Write rules for yourself that prevent the same mistake  
- Ruthlessly iterate on these lessons until mistake rate drops  
- Review lessons at session start for relevant project  

---

### 4. Verification Before Done
- Never mark a task complete without proving it works  
- Diff behavior between main and your changes when relevant  
- Ask yourself: "Would a staff engineer approve this?"  
- Run tests, check logs, demonstrate correctness  

---

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"  
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"  
- Skip this for simple, obvious fixes - don't over-engineer  
- Challenge your own work before presenting it  

---

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding  
- Point at logs, errors, failing tests - then resolve them  
- Zero context switching required from the user  
- Go fix failing CI tests without being told how  

---

## Task Management
1. **Plan First**: Write plan to `tasks/todo.md` with checkable items  
2. **Verify Plan**: Check in before starting implementation  
3. **Track Progress**: Mark items complete as you go  
4. **Explain Changes**: High-level summary at each step  
5. **Document Results**: Add review section to `tasks/todo.md`  
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections  

---

## Core Principles
- **Simplicity First**: Make every change as simple as possible. Impact minimal code  
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards

---

## Running the Simulator

**Always use the venv Python**: `./venv/bin/python` (not system `python`). Pygame and other deps are installed there.

### Headless run (default — use this for any programmatic run)
`agv_simulation/headless.py` has **no CLI entry point**; it exposes `run_headless()` as a function. Invoke with a `-c` one-liner:

```bash
./venv/bin/python -c "
from agv_simulation import run_headless
result = run_headless()  # defaults: 10 AGVs, 25 carts, 28800s sim, 0.1s tick
for k, v in result.items():
    print(f'{k}: {v}')
"
```

- Default 8-hour sim completes in ~35–40s wall time. Use `timeout=600000` on the Bash call to be safe.
- Output is **huge** (~1 MB of per-tick dispatcher logs). Pipe through `tail -80` or save to a file — don't dump into context.
- Results are auto-appended to `results/sim_results.md` on completion.
- Override any arg: `run_headless(num_agvs=8, num_carts=20, sim_duration=3600, tick_dt=0.1)`.
- **Spawn model (policy-fair)**: carts enter the world AT the Box Depot — 8 tiles fill at t=0, then one cart per 5 sim-s into any depot tile that is free and not targeted by an in-flight job, until `num_carts` have entered. AGVs stream in single-file through the spawn tile (next spawns only when the previous has driven off). Identical in GUI and headless, so results are directly comparable. There is no cart-spawn tile anymore.
- **Dynamic highway (this branch)**: the two vertical highway pillars are movable. Pass `run_headless(highway=(left, right))` (default `(23, 52)`; bounds: left ≥ 16, right ≤ 70, gap ≥ 17). Stations, station racking/parking, aisle-bank boundaries, SKU spread, zoning and walk distances all follow the pillars (`agv_simulation/layout.py`, singleton `get_layout()`/`set_layout()`). In the GUI, drag a pillar column sideways with the mouse — the world rebuilds per column step (same reset semantics as the slotting toggle) and each station shows its longest one-way pick walk (`≤NNm` label, `Catalog.longest_walk_m()`).
- **Controlled experiments**: pass `seed=42` for a deterministic order stream (order N is identical across runs/policies — required for fair A/B), and `strategies={'eta_reservations': True, 'global_assignment': True}` (any subset) to enable dispatch strategy modules (`agv_simulation/strategies/`). All off = baseline. GUI has the same toggles as clickable switches (seeded 42 by default). Travel-window sequencing over true directed distances (reverse-BFS `DistanceMap`) is NOT a toggle — it's baked into the baseline dispatcher (`_travel_window`, `TRAVEL_WINDOW=3`).

### Strategy A/B comparison
```bash
./venv/bin/python experiments/run_strategy_comparison.py            # 3 configs x 8 combos x 3 seeds, 8h
./venv/bin/python experiments/run_strategy_comparison.py --quick    # 2h sims
```
Appends per-config tables to `results/strategy_comparison.md`.

### Per-strategy fleet optimization
```bash
./venv/bin/python experiments/run_fleet_optimization.py             # 2-stage: coarse fleet grid + 3-seed confirm
```
Finds each strategy combo's own optimal (AGVs, carts) — policies change congestion
behavior, so their throughput-maximizing fleets differ. Appends to
`results/fleet_optimization.md`. Sweep runs use `run_headless(..., export=False)`
so they don't spam `results/sim_results.md`.

### Parameter sweep
```bash
./venv/bin/python sweep.py                                          # default grid
./venv/bin/python sweep.py --agvs 4,8,12 --carts 8,16,24 --duration 3600
./venv/bin/python sweep.py --parallel --workers 8 --csv results.csv
```

### Interactive GUI (only when the user explicitly asks)
```bash
./venv/bin/python -m agv_simulation
```
- **Do not run this autonomously**: it opens a pygame window, never terminates on its own, and only writes results via `dispatcher.export_results()` on window close. Ask the user to run it themselves with `! ./venv/bin/python -m agv_simulation`.
- Controls: A=spawn AGV, C=spawn Cart, P=pickup, R=return, TAB=cycle, Space=pause, T=auto-spawn, Up/Down=speed, D=debug dump, Q=quit.

### Key result fields
`completed_orders`, `orders_per_hour`, `avg_cycle_time`, `agv_utilization`, `agv_blocked_fraction`, `station_fill` (per-station fill_rate — watch for 100% = bottleneck, 0% = under-used).