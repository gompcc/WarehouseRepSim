# ⚡ SESSION HANDOFF — read this first (2026-07-14, end of picker/slotting session)

Everything below this block is historical context from two parallel
workstreams (dispatch strategies + picker/aisle model), both now MERGED and
COMMITTED through `3f27a16`. Tree was clean at handoff except `.claude/`.

## State of the world
- Pickers fully integrated: carts leave a station only when their SKU lines
  are picked (90s flat rule DELETED). Seeded 1h baseline: 23 orders/hr,
  pickers 81% busy (binding constraint), 0 left early. 60 tests green.
- 2000 SKUs with half-normal popularity (SKU 1 ≈ 90× SKU 2000); orders =
  max(1, round(N(20, 9))) SKUs sampled popularity-weighted in **SKU space**
  (user-set 2026-07-14; implements EXPERIMENT_DESIGN F1 — identical demand
  across slotting arms, checksum-verified; stations visited are derived,
  now ~6.5–7.4 mean). BOX_DEPOT_TIME 45→60 s (user-set). New seeded 1h
  baseline: 19 orders/hr, cycle 38.6 min, pickers 0.59 busy (constraint
  shifted toward transport), 0 left early. Old numbers NOT comparable.
- 4 slotting strategies toggleable via `run_headless(slotting=...)`:
  demand-weighted one-way walk = sequential 17.1 m | aisle_proximal 17.0 m |
  fibonacci 18.0 m (WORSE — pickers launch from stations, not the track) |
  velocity 13.1 m (−23%, the lower bound). Calibration constants FROZEN
  (aisles.WALK_TIME_FIXED/SCALE) — placement experiments measure walk deltas.
- Experiment methodology: `experiments/EXPERIMENT_DESIGN.md` (paired seeds,
  warm-up exclusion, fairness rules, ranked new dispatcher strategies —
  picker-aware dispatch first). NOTE its fairness catch: orders sample SKUs
  within station zones, so slotting changes the demand stream — generate
  orders in SKU space before running Matrix A.

## Remaining task queue (mirrors the session task list #7–#15)
- [x] **Logging/storage revamp** — DONE (2026-07-14): EventLog keeps only
      stuck/teleport in memory (counters unaffected), `run_headless` gains
      `snapshot_interval=60.0` → `"snapshots"` time series +
      `results_json=` per-run JSON dump (`results/runs/`, gitignored),
      18 dispatcher / 1 env / 1 picker INFO → DEBUG, returns now include
      `order_completion_times` + `picker_stats["per_station"]`. Verified
      behavior-identical (seed-42 1h: 24 orders / 1568.4s avg cycle, exact
      match vs stashed pre-change code); 60 tests green.
- [ ] **Placement visualization** — map colored by SKU popularity per
      slotting strategy (show the fibonacci rings around the track) + bar
      graph comparing avg picker walk time: sequential vs aisle-proximal vs
      fibonacci (vs velocity). Use the dataviz skill for chart styling.
      Also: GUI should display the active slotting strategy name.
- [ ] **Station/aisle zone color-coding (user request)** — each S station
      gets a color; each racking run's border colored by the station owning
      its slots, per face (N/S side of a run can differ; a face split
      between stations gets segmented borders). Legend on map.
- [ ] **Picker strategies as experiment toggles (user request)** — (a)
      STATIC: picker bound to a station + its aisles (current); (b) DYNAMIC:
      pickers roam, serving the carts that most improve throughput
      (inter-station walking counted). Headless + GUI toggles; add to the
      experiment matrix.
- [ ] **Integration sweep** — seeded runs per slotting × picker strategy,
      GUI snapshot, no stuck pathologies, tests green.
- [ ] **Cleanup (subagents)** — dead code, efficiency sweep (dispatcher
      scans, picker updates), eliminate happy-path-only testing.
- [ ] **Run experiments + 2-page findings doc** — per
      EXPERIMENT_DESIGN.md: §product layout, §dispatcher strategies,
      4–6 decision-grade figures (walk-time bar chart required).

Multi-session warning: another Claude session may share this working tree
and branch — check `git status` for foreign changes before editing/committing;
stage only files whose diff is yours (see memory: concurrent-sessions-same-worktree).

---

# Toggleable Dispatch Strategy Modules (2026-07-14)

Goal: prove throughput impact of three dispatch strategies, each an isolated
module toggleable at runtime (GUI switches + headless config), under a
controlled environment (seeded, deterministic order stream):

1. **ETA reservations** — score stations by *predicted* fill at the cart's
   arrival time (departures + inbound reservations + true directed travel
   time), not current fill. Live per-station forecast shown on the map.
2. **Global assignment** — Hungarian matching of all free AGVs × all pending
   jobs at once (pure-python, no scipy), replacing greedy nearest-first.
3. **Order sequencing** — restrict station choice to a forward window in
   anti-clockwise loop order (directed distances), preventing backward laps.

Key map fact driving all three (corrected during implementation): Manhattan
distance is a fair proxy *within* a station bank (bidirectional parking
ladders), but underprices left↔right cross-bank trips ~2x — banks connect
only via the top/bottom highways. `DistanceMap` (reverse-BFS) gives true
directed distances.

## Plan
- [x] Seeded orders: per-order deterministic RNG in models.py; `seed` param in
      run_headless; golden baseline captured from HEAD worktree (monkeypatched
      seeding) BEFORE dispatcher refactor
- [x] `agv_simulation/strategies/` package: config.py (StrategyConfig +
      registry), distances.py (reverse-BFS directed distance maps),
      eta_reservations.py, global_assignment.py (Hungarian),
      order_sequencing.py
- [x] Dispatcher integration: `_choose_next_station()` seam (3 call sites),
      `_assign_jobs` delegation, per-tick ETA forecast cache for display
- [x] Regression proof: seed=42 toggles-off 2h run identical to golden
      (93 orders, 46.5/hr, avg cycle 1567.95s — exact match); 42 tests green
      (10 new: Hungarian vs brute force, seeded-order determinism, distance
      map, sequencing, toggle isolation)
- [x] Headless: `strategies=` param; results export lists active strategies +
      seed
- [x] GUI: STRATEGIES panel section w/ mouse-clickable toggles, live
      orders/hr graph strip under map (900s rolling window, toggle-flip
      markers), predicted-fill "→n.n" labels at each S station when ETA on;
      verified via SDL dummy-driver render + snapshot
- [x] Controlled A/B experiment round 1 (14/25 only): SEQ +1.7%, HUN -0.6%,
      ETA -2.0% — station-saturated config compresses policy deltas; ETA
      FILL_WEIGHT=120 repeated lessons.md iteration-11 mistake, reset to 30
- [x] A/B round 2 (FILL_WEIGHT=30): 3 configs (14/25, 10/25, 10/15) × 8
      combos × 3 seeds → results/strategy_comparison.md
- [x] Bonus 16/25 record check (experiments/check_16agv.py)
- [x] Review section below with demonstrated numbers

## Review / Results

Demonstrated throughput impact (8h sims, 3 seeds each, identical seeded
order streams; full tables in results/strategy_comparison.md):

| Config | Best combo | Orders/hr | vs baseline | Note |
|---|---|---|---|---|
| 14 AGVs / 25 carts | ETA | **84.2** | **+4.9%** | seed ranges disjoint from baseline |
| 16 AGVs / 25 carts | ETA(+HUN) | **90.9** mean, **92.4** peak | +2.3% | new all-time best (old record 89.5) |
| 10 AGVs / 15 carts | ETA+HUN | **58.9** | **+3.7%** | ranges disjoint; cycle 15.4→14.9m |
| 10 AGVs / 25 carts | ETA+HUN+SEQ | 55.8 | +2.7% | congestion-dominated, noisy |

- ETA reservations is the consistent winner in every regime; Hungarian is
  neutral alone but composes with ETA when transport-bound; sequencing is a
  small consistent positive alone (+0.4–1.8%).
- Round 1 failure documented in lessons.md iteration 20: FILL_WEIGHT=120
  made ETA -2%; recalibrating to the baseline's weight (30) flipped it to +4.9%.
- Verification: refactored dispatcher with all toggles off is byte-identical
  to pre-refactor code (seed-42 golden run: 93 orders / 46.5/hr / 1567.95s
  avg cycle, exact match). 42 tests pass (10 new).
- GUI verified via SDL dummy-driver snapshot: toggle switches, live
  orders/hr strip with toggle-flip markers, per-station "→n.n" ETA forecasts.

---

# Picker & Product Aisle Model (2026-07-14) — PAUSED (superseded for now by strategy-module work above)

(Previous plan — Environment/Dispatcher separation — is complete; see git
history of this file and results/sim_results.md.)

Goal: add three banks of bi-level picking aisles (per user's sketch), a
2000-SKU catalog with one slot per SKU, SKU-based orders (1–40 lines), and
per-station pickers whose walking time (1.4 m/s + 10 s grab, one SKU line per
round trip, aisles enterable only at the ends) determines cart dwell time at
stations. Full spec: **PRD Section 14**.

Decisions locked with user (2026-07-14):
- Expand grid to 86 cols (+14 west, +12 east), TILE_SIZE 20→16 px
- 1 picker per station (sweepable constant)
- 1.4 m/s walk + 10 s grab, replaces flat PICK_TIME_PER_ITEM=90s
- SKU→station zoning by nearest walking distance

## Plan
- [x] Commit prior session's uncommitted work separately
- [x] Document design in PRD Section 14 + this plan (commit)
- [x] **Stage 1 — grid expansion** (commit 22b1450): all coords +14,
      TILE_SIZE 16, GRID_COLS 86. Verified behavior-preserving: seeded 1h
      run identical to baseline (38 orders/hr, 2.1% blocked, 27 stuck);
      32 tests pass.
- [x] **Stage 2 — aisles module** (commit d11b838): aisles.py, exactly 2000
      slots @ 0.894 m across 894 m of pick face, nearest-station zoning
      (S1: 148 … S7: 390 SKUs), one-way walks 6–35 m, AISLE_RACK tiles
      rendered as dark bars; snapshot matches sketch.
- [ ] **Stage 3 — PAUSED (user, 2026-07-14)** until the dispatch-strategy
      work above stabilises dispatcher.py — then: Order → 1–40 SKU ids with derived
      stations_to_visit; picker.py (per-station FIFO, walk/grab cycle,
      release rule → cart.picking_complete); dispatcher MOVE_TO_PICK /
      PICKING integration; environment tick + stuck-watchdog exemption;
      renderer picker dots; headless + export picker metrics. Commit.
- [ ] **Stage 4 — verify**: pytest, 8h headless run, new snapshot, sanity-check
      walk times (~10–40 m round trips), record results below. Commit.

## Review / Results
(to be filled in as stages complete)

---
## ⚠️ Note from parallel session (env-separation work, 2026-07-14)

**Please commit your aisle/strategies work soon** — user request. `aisles.py`
and `strategies/` are still *untracked*: if this session is interrupted they
are lost entirely, and the tracked-file edits (dispatcher, environment,
models, renderer, …) are only recoverable as one undifferentiated diff.
Commit per completed stage as you did with 22b1450. A checkpoint/WIP commit
of the current state is fine too — everything of mine is already committed
(latest: eced760), so the tree's dirty state is 100% yours to snapshot.

## Addendum: per-strategy fleet optimization (2026-07-14, follow-up question)

User asked whether each strategy combo might want a different fleet size.
Yes — evidence: HUN negative at 14/25 but positive at 10/15; ETA lowers
blocked% so it likely sustains more AGVs before the congestion cliff.

- [x] `run_headless(..., export=False)` so sweeps don't spam sim_results.md
- [x] experiments/run_fleet_optimization.py — two-stage: 5x4 fleet grid
      (AGVs 10-18, carts 15-30) x 8 combos, seed 42 screening; top-3 per
      combo confirmed on seeds 11/77; per-combo optimum + at-own-optimum
      comparison → results/fleet_optimization.md
- [ ] Record findings here + lessons.md when the run completes

## Addendum 2: policy-fair spawn model (2026-07-14, user request)

Old model teleported AGVs onto 10 handpicked parking spots and trickled
carts in from a west-edge spawn tile — both potentially favor some policies.
New model (identical GUI + headless):
- [x] Carts spawn AT the Box Depot: 8 tiles fill at t=0, then 1 per 5 sim-s
      into any tile that is free AND not targeted by an in-flight job
      (dispatcher publishes job_targets() → env.reserved_targets each tick);
      spawned carts start AT_BOX_DEPOT with the full 45s load timer, then an
      AGV must collect them. Legacy cart-spawn tile removed from the map.
- [x] AGVs stream in single-file via AGV_SPAWN_TILE — next spawns only once
      the previous has left the tile. place_agvs()/DEFAULT_AGV_SPOTS removed.
- [x] 6 new tests (53 total green); 1h smoke run clean (0 teleports);
      GUI render verified under new model
- [ ] Fleet optimization re-run under new model (in progress) — per-combo
      optimal fleet + at-own-optimum comparison
NOTE: absolute o/hr numbers are NOT comparable with pre-spawn-model results
(first-hour throughput is higher — no west-edge ferry leg; AGV ramp-in).
