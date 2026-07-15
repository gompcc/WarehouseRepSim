# Dispatcher Optimization Log

## Current Record
- **Peak throughput**: 89.5 orders/hr (pre-aisle-redesign map)
- **Config**: 16 AGVs, 25 carts, 28800s duration
- **Date**: 2026-07-14
- **Commit**: a85216d (Environment separation + deadlock-trap fixes, iterations 18-19)

## Architecture Constraints (do not try to change these)
- Highway cols 9/38 are single-lane, anti-clockwise loop — fundamental map constraint
- Pack-off has limited physical tiles — throughput ceiling is real
- AGV_SPEED is a rendering constant, not a tuning knob

## Failed Approaches (from initial development, pre-optimization loop)
- **Buffer cooldown timers**: Added 30s cooldown before re-dispatching buffered carts. Caused idle carts sitting in buffers while stations were free. Removed.
- **Dispatch attempt counters**: Tracked attempts per cart, gave up after N. Carts got permanently stuck. Removed.
- **Minimum retarget distance**: Required retarget to be >N tiles away. Prevented nearby valid tiles from being used. Removed.
- **Removing MAX_CONCURRENT_DISPATCHES entirely**: Caused highway gridlock — too many AGVs dispatched at once overwhelmed single-lane highways. Restored with backpressure.
- **Pre-spawning all carts at once on same tile**: 25 carts stacked at (0,7). Massive congestion. Changed to one-at-a-time spawning.
- **Reducing PACKOFF_TIME below 20s**: Already reduced from 60s to 20s which was the biggest single throughput gain. Further reduction would be unrealistic for the physical process being modeled.

---
<!-- New iterations go below this line -->

### Iteration 1: Job Priority Ordering — SUCCESS

- **Hypothesis**: Prioritizing pending jobs by lifecycle stage (completion-path first) will improve throughput because RETURN_TO_BOX_DEPOT and MOVE_TO_PACKOFF jobs free carts for reuse, while MOVE_TO_BUFFER jobs are low-value moves.
- **Change**: Added `_JOB_PRIORITY` dict and `self.pending_jobs.sort()` in `_assign_jobs()` before the assignment loop.
- **Result**: 48.5 orders/hr (was 38.0) | blocked% 1.9% (was unknown) — peak at 12 AGVs, 25 carts
- **Analysis**: Massive 27.6% throughput gain. By serving completion-path jobs first, carts recycle faster through the system. The 12/20 config went from 38.0 to 48.0, and 12/25 peaked at 48.5. Diagnostic run at 12/25 hit 51.0 (variance).
- **Key insight**: Job scheduling order has enormous leverage — the dispatcher was wasting AGV capacity on low-priority buffer moves while high-value completion jobs waited.

### Iteration 2: Weighted Station Scoring — SUCCESS

- **Hypothesis**: Replacing rigid fill-rate tiers with `score = fill_rate * 30 + distance` will improve throughput by avoiding unnecessary cross-warehouse trips when a nearby station has acceptable capacity.
- **Change**: Replaced 3-tier priority system in `_pick_best_station()` with continuous weighted score.
- **Result**: 56.5 orders/hr (was 48.5) | blocked% 3.8% at peak (14 AGVs, 25 carts). Diagnostic confirmed 54.0 (variance).
- **Analysis**: 16.5% gain. The biggest improvement was at 14 AGVs — the 14/15 config jumped from 32.5 to 43.5 (+34%). By keeping carts on the same side of the warehouse, total travel distance dropped and more AGVs could operate without congesting highways. Optimal config shifted from 12 to 14 AGVs.
- **Key insight**: Distance weighting in station selection has multiplicative effects — shorter trips → less highway time → less congestion → more AGVs sustainable.

### Iteration 3: Dynamic Dispatch Cap — FAILURE

- **Hypothesis**: Making MAX_CONCURRENT_DISPATCHES scale with AGV count (`max(12, len(agvs))`) will improve throughput by letting all AGVs operate when congestion is low.
- **Change**: Replaced `MAX_CONCURRENT_DISPATCHES` constant with `max(MAX_CONCURRENT_DISPATCHES, len(agvs))` in `_assign_jobs()`.
- **Result**: 55.0 orders/hr (was 56.5) | 14/25 cratered from 56.5 to 40.0 (blocked% 4.9%)
- **Analysis**: Removing the cap helped low-cart configs (14/15: 43.5→49.5) but badly hurt high-cart configs. With 25 carts generating many simultaneous jobs, all 14 AGVs were dispatched at once, overwhelming single-lane highways.
- **Key insight**: MAX_CONCURRENT_DISPATCHES=12 is a safety valve, not a bottleneck. The cap prevents highway gridlock when job volume is high — don't raise it without congestion-aware dispatch.

### Iteration 4: Lower Off-Highway Cost — FAILURE

- **Hypothesis**: Reducing off-highway tile cost from 10 to 4 will allow AGVs to take parking-tile detours around congested highway segments.
- **Change**: Changed edge_cost in `astar()` from 10 to 4 for non-highway tiles.
- **Result**: 52.5 orders/hr (was 56.5) | blocked% 8.4% at 12/25 (was 5.2%)
- **Analysis**: AGVs started routing through parking areas more, but this caused MORE congestion in non-highway tiles. 14/15 cratered from 43.5 to 31.0. The high off-highway penalty (10x) is correct — it keeps AGVs on the efficient highway loop.
- **Key insight**: Off-highway tiles should stay expensive — routing AGVs through parking causes congestion with parked carts and other AGVs. The highway is single-lane but efficient; the penalty correctly steers traffic there.

### Iteration 5: Smart Idle AGV Pre-positioning — FAILURE

- **Hypothesis**: Pre-positioning idle AGVs near carts about to finish processing (timer < 30s) will reduce response time and improve throughput.
- **Change**: Extended `_park_idle_agvs()` to detect carts with low timers and move idle AGVs near them.
- **Result**: 21.5 orders/hr (was 56.5) | blocked% up to 22.4% — catastrophic regression
- **Analysis**: AGVs constantly moving to pre-position flooded the highways with unnecessary traffic. Every completed pre-positioning move triggered another one, creating a feedback loop of constant movement. The original approach (only park AGVs that are on highway tiles) is correct — idle AGVs on parking tiles should stay put.
- **Key insight**: NEVER create unnecessary AGV movement. Each movement consumes highway capacity. Idle AGVs parked off-highway cost nothing — moving them "proactively" has massive negative externalities on highway throughput.

### Iteration 6: Faster Reroute Timeouts — SUCCESS

- **Hypothesis**: Reducing BLOCK_TIMEOUT from 3.0s to 1.5s and REROUTE_COOLDOWN from 2.0s to 1.0s will reduce wasted blocked time.
- **Change**: Two constants in `constants.py`.
- **Result**: 58.5 orders/hr (was 56.5) | blocked% comparable at peak. 12/15 jumped from 49.0 to 51.5.
- **Analysis**: 3.5% gain. Faster rerouting resolves blockages more quickly, keeping AGVs productive. Most configs improved. The reduced cooldown doesn't cause excessive rerouting because A* already finds good alternative paths.
- **Key insight**: Reroute timing is a cheap knob — faster detection and resolution of blocks directly converts to throughput.

### Iteration 7: Faster Job Cancel Timeout — FAILURE

- **Hypothesis**: Reducing JOB_CANCEL_TIMEOUT from 30s to 15s will free stuck AGVs faster.
- **Change**: One constant in `constants.py`.
- **Result**: 54.0 orders/hr (was 58.5) | 14/25 dropped from 58.5 to 49.0
- **Analysis**: Faster cancellation causes too much job churn. Jobs that would resolve naturally in 15-20s get cancelled and re-queued, adding pickup/dropoff overhead and highway traffic from the replacement AGV. The 30s timeout is correct — it's long enough that only truly stuck jobs get cancelled.
- **Key insight**: JOB_CANCEL_TIMEOUT should stay at 30s. Patience pays off — most blocks resolve within 15s via rerouting.

### Iteration 8: Faster Spawn Interval — FAILURE

- **Hypothesis**: Reducing PRELOAD_SPAWN_INTERVAL from 5.0s to 2.0s will get carts into the system sooner.
- **Change**: One constant in `constants.py`.
- **Result**: 57.0 orders/hr (was 58.5) | marginal regression within variance
- **Analysis**: Faster spawning causes slight initial congestion burst at spawn area and Box Depot. The 75s saved (125s→50s ramp-up) is negligible in a 7200s simulation (~1%). Not worth the initial congestion cost.
- **Key insight**: Spawn rate tuning is a dead end — the ramp-up period is too small relative to total sim duration to matter.

### Iteration 9: Progress-Based Cart Priority — FAILURE

- **Hypothesis**: Prioritizing carts by order completion progress in `_create_jobs()` (most-complete first) will speed up cart recycling.
- **Change**: Sort carts by `(-completed_stations, -times_buffered)` with boost for pack-off-ready carts.
- **Result**: 54.5 orders/hr (was 58.5) | 14/25 dropped from 58.5 to 45.5
- **Analysis**: Creates convoy effect at Pack-off. Many near-complete carts arrive simultaneously, overwhelming the 4-tile Pack-off capacity. Meanwhile early-cycle carts are starved of station tiles. The original buffered-cart priority is better balanced.
- **Key insight**: Cart priority in `_create_jobs` should prioritize starvation prevention (times_buffered) not throughput optimization. Throughput optimization belongs in `_assign_jobs` (job priority ordering).

### Iteration 10: Target-Aware Buffer Placement — FAILURE

- **Hypothesis**: Buffering carts near their target station (not current position) will reduce pickup distance when the station opens.
- **Change**: Modified buffer spot search to use target station position in `_create_jobs()`.
- **Result**: 52.5 orders/hr (was 58.5) | blocked% increased across all configs
- **Analysis**: Buffering near the target station INCREASES the initial buffer trip distance (cart has to cross the warehouse now). The benefit of shorter future pickup doesn't materialize because (a) the buffer is still not AT the station, and (b) carts may get re-buffered. Minimizing current trip cost beats speculative future savings.
- **Key insight**: Buffer near current position, not target. Minimize the trip you're making NOW — don't speculate about future trips.

### Iteration 11: Station Weight Tuning — FAILURE

- **Hypothesis**: Tuning the fill-rate weight (tried 15.0 and 45.0, vs current 30.0) will better balance station load vs travel distance.
- **Change**: Modified `rate * 30.0 + dist` to `rate * 15.0` then `rate * 45.0`.
- **Result**: weight=15: 57.5/hr (was 58.5). weight=45: 48.0/hr. Both worse than 30.0.
- **Analysis**: weight=30 is already well-calibrated. Lower weight over-clusters carts at nearby stations, higher weight causes too many cross-warehouse trips (back to the original problem).
- **Key insight**: The fill-rate weight of 30.0 is near-optimal and should not be tuned further.

### Iterations 12-13: Backpressure Tuning — FAILURE

- **Hypothesis**: Changing backpressure divisor from //3 to //4 (lighter) or //2 (heavier) will improve throughput.
- **Result**: //4 → 54.5/hr, //2 → 55.5/hr (both worse than 58.5/hr)
- **Key insight**: Backpressure divisor of 3 is well-calibrated. Don't tune further.

### Iteration 14: Sidetrack Overflow Lanes — SUCCESS

- **Hypothesis**: Reducing path cost for parking tiles adjacent to highway cols (8, 10, 37, 39) from 10 to 2 will create overflow lanes, reducing highway congestion without affecting general routing (unlike iteration 4 which reduced ALL off-highway costs).
- **Change**: Added `_SIDETRACK_COLS` set in `pathfinding.py`. Parking tiles in these columns get cost=2 instead of 10.
- **Result**: 62.0 orders/hr (was 58.5) | blocked% 3.0% (was 5.2%) — peak at 14 AGVs, 25 carts. Diagnostic confirmed 61.0.
- **Analysis**: 6% gain. The key difference from iteration 4: only tiles ADJACENT to the highway get reduced cost, and only PARKING tiles (not station tiles). This creates narrow overflow lanes that AGVs use to bypass congested highway segments, without routing through stations or far-off parking areas.
- **Key insight**: Surgical cost reduction (specific cols + specific tile types) works where global cost reduction (iteration 4) failed. The overflow lanes are the right granularity — wide enough to help but narrow enough to avoid side effects.

### Iteration 15: East/North Sidetrack Lanes — FAILURE

- **Hypothesis**: Extending sidetrack lanes to rows adjacent to east/north highways will further reduce congestion.
- **Change**: Added `_SIDETRACK_ROWS` for rows 6, 8, 37, 39 with cost=2 for parking tiles.
- **Result**: 60.0 orders/hr (was 62.0) | blocked% dropped to 1.5% (below 2% target!)
- **Analysis**: While blocked% improved, throughput dropped. The north highway sidetracks (rows 6, 8) are near Box Depot and Pack-off — reducing costs there diverts AGVs from efficient highway routes. Column sidetracks work because the vertical highways (cols 9, 38) are the primary bottlenecks, not the horizontal ones.
- **Key insight**: Only add sidetracks where congestion is proven. The vertical highways are the bottleneck; horizontal highways have less contention.

### Iteration 16: Reduced Blocker Patience — FAILURE

- **Hypothesis**: Reducing wait time behind moving blockers from `BLOCK_TIMEOUT * 2` to `* 1.5` will trigger reroutes sooner.
- **Change**: One constant multiplier in `_handle_blocked_agvs()`.
- **Result**: 56.5 orders/hr (was 62.0) | 14/25 cratered from 62.0 to 41.5
- **Analysis**: Too-aggressive rerouting behind moving blockers wastes path calculations and creates longer paths. The blocker usually clears in <3s anyway. The current `BLOCK_TIMEOUT * 2 = 3.0s` patience is correct.
- **Key insight**: Patience behind moving blockers is important. Most blocks by moving AGVs resolve naturally in 1-3s — rerouting is expensive and counterproductive.

### Iteration 17: Skip Station Buffer — FAILURE

- **Hypothesis**: When a cart finishes at a pick station and its next station is full, letting it wait in place (instead of buffering) will reduce unnecessary moves and improve throughput.
- **Change**: Removed buffer job creation in `_create_jobs()` for PICKING-state carts whose next station is full. Cart stays at current tile instead.
- **Result**: 55.5 orders/hr (was 62.0) | regression across all configs
- **Analysis**: Carts waiting at stations block the station tile, preventing other carts from being processed there. Buffering to a nearby parking spot frees the station tile for productive use. The buffer move is NOT wasted — it's essential for station throughput.
- **Key insight**: Always buffer carts away from station tiles when the next station is full. Station tile occupancy is a critical resource — never let a waiting cart block it.

### Iteration 18: Environment/Dispatcher Separation + Stuck-Cart Bug Hunt — SUCCESS

- **Hypothesis**: Carts were getting permanently stuck (log showed C19 buffered 50x, avg cycle computed from 13 of 347 orders). Instrumenting the environment and fixing lifecycle holes should recover lost fleet capacity.
- **Change**: New `environment.py` (Environment owns world state/stepping/spawning; structured JSONL event log; stuck-cart watchdog; physics guard detecting cart teleports). Headless + GUI now drive the same Environment. Dispatcher fixes: orphan recovery (WAITING cart with `order=None` matched NO dispatch branch → deadlocked forever; 4/25 carts dead in an 8h run), `Order.packed` flag (aborted returns were re-sent to Pack-off), cycle-time stamped every cycle, give-up releases cart at AGV's position (was teleporting), buffer spots exclude AGV-occupied tiles, retargets spaced out (were burning 3 attempts in 0.3s).
- **Result**: 10/25: 43.4 → ~53 orders/hr. 14/25: 77.7–81.0 (was 43–62). Stuck events 485 → 73 at 14/25; teleports 0.
- **Key insight**: The biggest losses weren't congestion — they were *state-machine holes* that permanently killed carts. Every cart lifecycle state × (order status) combination must map to a recovery job. The environment-level watchdog (no progress for 300s → event) found in minutes what weeks of throughput tuning missed.

### Iteration 19: Map-Graph Deadlock Traps — SUCCESS (environment fix)

- **Hypothesis**: A 10/25 run froze entirely at t≈1060s (0.1 orders/hr). Suspected AGV-level deadlock, not dispatcher policy.
- **Change**: Seed-0 repro + full AGV state dump showed a head-on 2-cycle: junction (9,7) had a westbound edge into (8,7) while row 7 cols 1–8 flow east into (9,7) — two AGVs met and froze the single connector between the NW corridor and the loop; everything queued behind. Also found row 8 cols 1–8 dead-ends at (1,8) with zero outgoing edges (permanent AGV trap). Removed the westbound junction edge; added merge-north edges from the row-8 return lane.
- **Result**: 12/12 seeds complete cleanly (382–440 orders/8h at 10/25). Scaling now works: 16 AGVs/25 carts → **89.5 orders/hr** (new record, was 62.0). 16/30 → 85.5 (more carts hurt: congestion).
- **Key insight**: Separate environment defects from dispatcher quality. Both freezes looked like "dispatcher gridlock" but were *map topology bugs*. New map-agnostic invariant tests (no sink nodes, full mutual reachability, no head-on 2-cycle without an alternative route) now guard any future layout — important for the aisle redesign.
- **Note for aisle-map session**: junction coordinates in `build_graph` and coordinate-hardcoded tests must shift with the +14-col migration; the three graph-invariant tests in `test_collision_avoidance.py` are coordinate-free and must stay green.

### Iteration 20: Toggleable Strategy Modules (ETA / Hungarian / Sequencing) — SUCCESS (ETA)

- **Hypothesis**: Three structural fixes as isolated toggleable modules (`agv_simulation/strategies/`): (1) ETA reservations — score stations by predicted occupancy at arrival (subtract departing occupants, true directed travel times) instead of current fill; (2) Hungarian global AGV↔job matching; (3) travel-ordered sequencing window.
- **Method**: Seeded order streams (order N identical across policies — `set_order_seed`), 8 toggle combos × 3 seeds × 3 configs × 8h, refactor proven behavior-preserving (seed-42 run byte-identical to pre-refactor golden run).
- **Result**: ETA is the consistent winner: **+4.9%** at 14/25 (84.2 vs 80.3, seed ranges disjoint), **+2.3%** at 16/25 (new best: mean 90.9, peak **92.4 o/hr** with ETA+HUN), +3.7% at 10/15 (ETA+HUN, ranges disjoint), +1.4% at congested 10/25. HUN alone ≈ neutral (greedy nearest was already decent); helps composed with ETA in transport-bound configs. SEQ alone +0.4–1.8%.
- **First attempt failed**: FILL_WEIGHT=120 made ETA *negative* (-2%) — repeated iteration 11's mistake (over-weighting fill vs distance chases empty stations cross-warehouse). Reset to 30 (baseline calibration) → +4.9%. Check lessons before choosing constants.
- **Map insight (corrects the "one-way loop" story)**: parking/pick columns are bidirectional ladders, so Manhattan is fine *within* a bank; it underprices left↔right cross-bank trips ~2x (banks connect only via top/bottom highways). This is why directed-distance ETA scoring beats Manhattan scoring.
- **Key insight**: predicting *departures* (cart finishing picks + haul-away overhead) is the valuable half of ETA scoring — inbound reservations were already counted by the baseline. At station-saturated configs the win comes from routing carts to stations that are about to free up rather than bouncing to the far bank.

## 2026-07-15 — dynamic-highway bug sweep lessons
- **Golden-diffing only proves the DEFAULT configuration.** Parameterizing
  hardcoded geometry passed a byte-identical golden check yet still broke
  layouts where a range-conditioned rule (depot north exits, 29≤x≤36) fell
  on the other side of the moved parameter — the eastbound lane never got
  the exits the westbound lane had. When a constant becomes a variable,
  re-derive EVERY rule keyed to ranges it can cross, and stress-test the
  parameter's extremes (L=53/R=70 gridlocked at 0 orders), not just the
  default.
- **Mutable identity needs one source of truth.** Pickers re-homing
  (station_id) while crew lists stayed keyed by hire station silently
  corrupted management reviews and per-station stats (busy_fraction > 1.0).
  If an entity's home can change, membership structures must move with it.
- **Feature toggles that read cumulative counters must seed a baseline at
  flip time** (management ON mid-run divided all-picks-ever by one window).
