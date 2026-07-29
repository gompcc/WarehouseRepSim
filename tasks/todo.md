# SESSION 2026-07-29 — stations-per-order frontier (queue #1)

Continuing from the handoff queue below. Priority #1: attack STATIONS-PER-ORDER
(the real flat-demand constraint; balanced zoning A/B was negative because it
doesn't reduce stops). Analytic motivation: E[distinct stations] =
Σ(1−(1−p_i)^L); 9 balanced zones @ L=20 → 8.2 stops/order, 4 zones → 4.0,
3 zones → 3.0. Zone consolidation halves stops; sim must arbitrate the
trade-offs (longer picker walks, fewer parallel station slots, per-station
picker crowding).

## Plan
- [x] Explore: map zoning/order/dispatcher/picker seams (subagent).
      Key facts: Order.__init__ (models.py:121-129) buckets lines via
      catalog.station_of → stations_to_visit; dispatcher only consumes
      the set; walk_distance is geometric (any same-side station can
      pick any same-side slot, priced correctly); no split/batch code
      exists; 2-pager rec #4 already endorses zone-batched release.
- [x] Analytic pass: E[stops] math done inline (9 zones → 8.2 analytic;
      measured 6.71 — nearest zoning hoards + small orders)
- [x] Implement **zone-batched order release** toggle (`batch_release`)
      — commit 96f3e9f. Flag lives on Catalog (not models global) so
      station_avg_walk_s/longest_walk_m price the side-wide pool and
      auto-staffing stays honest. Order.__init__ consumes
      batched_release_map; rotation = order_id % n_side_stations.
      GUI toggle "Batched release (1 stop/side)" + run_headless kwarg
      + avg_stations_per_order result field.
- [x] Golden check: default 1h seed-42 EXACT pre/post match (19.999
      o/hr, cycle 2209.405s, 570 picks); 130 tests green (7 new)
- [x] A/B DONE — see results/batch_release_ab.md. **mgmt+extra+batch
      55.8 o/hr mean (3 seeds, ranges disjoint) vs 35.5 baseline =
      +57%; picks/hr ~1220 (new best; was ~950); st/ord 6.99→2.91;
      station saturation GONE (max fill 0.6). Batch alone ≈ +1.5 only
      — pair with management. Constraint moved to AGV transport
      (util 0.88-0.96, pickers 54% busy) → fleet refresh is next.**
- [x] Queue #2 DONE — pillar sweep re-run under the winning stack
      (70-layout screen + 2h×3-seed confirm): **OPTIMAL_HIGHWAY →
      (25, 68), 61.8 o/hr mean vs 55.8 default, ~1390 picks/hr**;
      wide span grows the 4-station central bank. Old (16,50) retired
      (commit 95848c8; results/highway_sweep.md).
- [x] Queue #5: EXPERIMENT_DESIGN.md — fixed stale 4-arm matrix counts
      + run budget; flat-demand update noted in F1 (the one remaining
      `velocity` mention is the deliberate deletion note)
- [x] Queue #3 DONE — fleet probe (experiments/run_fleet_probe.py,
      5×3 grid + 3-seed confirm + grid-edge check, all at L25/R68
      under the winning stack): **18A/30C = 93.3 o/hr mean /
      ~1990 picks/hr — THE 2000 PICKS/HR TARGET FLOOR IS REACHED**
      (seed 41 hit 2041). Plateau past 18 AGVs (~94 at 22A, util
      0.43) → constraint moved OFF transport again.
      OPTIMAL_FLEET[(False,False)] → (18, 30); ETA/HUN rows left but
      marked stale. results/fleet_probe.md.
- [x] Review section + handoff update

## Review / Results (2026-07-29)
Session total: 950 → ~1990 picks/hr best-known (2.1×), three stacked
levers, each verified on 3 seeds with disjoint/near-disjoint ranges:
1. Batched release (+57%): results/batch_release_ab.md, commit 96f3e9f
2. Pillar re-sweep L25/R68 (+11%): results/highway_sweep.md, 95848c8
3. Fleet 18A/30C (+51% over 10A/25C): results/fleet_probe.md
Full stack: batch+mgmt+extra @ L25/R68 @ 18A/30C = 93.3 o/hr.

NEXT FRONTIER — what binds at ~2030 picks/hr? AGV util is only ~0.5,
blocked ~2%, stations unsaturated. Candidates, in checking order:
(a) MANAGE_MAX_TOTAL=30 picker cap (~26 busy-equivalent needed at 39s
    side-wide walks — nearly binding; it's a policy constant, ask user
    before raising);
(b) station cart slots (5-6 with extra_slots) vs 93 carts/hr × 3 stops;
(c) Box Depot (60s × 8 tiles) / Pack-off dwell;
(d) pick-cycle time itself: 50 lines/picker/hr vs 240 target — walk
    39s side-wide; tighter batching (2 stations/side? demand-aware
    station choice with load spread?) trades stops for walk again.
Also still queued: #4 dynamic-pool re-A/B + relocation hysteresis
(designed, not implemented).

---

# ⚡ SESSION HANDOFF — dynamic-highway (read this first)
Written 2026-07-28 (work done 2026-07-14→15 sim-dates in run records).
Branch **feature/dynamic-highway**, worktree
`.claude/worktrees/dynamic-highway` (off main@2bd1f4f — NOT merged; main
untouched). ~25 commits, 123 tests green (`../../../venv/bin/python -m
pytest tests/ -q` from the worktree; `./venv` symlinks the main venv).
GUI: `./venv/bin/python -m agv_simulation` — user runs it via `!`, never
autonomously. Offscreen render checks work via `SDL_VIDEODRIVER=dummy`
(build world manually, call renderer, save PNG — see git log for recipes).

## What this branch adds (all committed, all tested)
1. **Movable highway pillars** — `agv_simulation/layout.py`:
   `HighwayLayout(left, right, extra_slots)` singleton
   (`get_layout`/`set_layout`), bounds L≥16 R≤70 gap≥17. Everything
   derives from it: stations/racking/parking, graph junctions, bank
   spans, zoning, labels. Drag pillars in the GUI (world rebuilds per
   column step); `run_headless(highway=(l,r))`. Default layout is
   byte-identical to the old fixed map.
2. **STRATEGIES toggles** (all rebuild-safe, crews/fleet/flags carry
   over via `restart_world` in `__main__.main`): Dynamic pickers
   (two-pool labour sharing: outer S1/S3+S5/S7/S9 crossing via
   SOUTH-ONLY detour below the East Highway, central S2/S4/S6/S8;
   relocation charges real time, crews RE-HOME on arrival), Picker
   management (auto-staffing: queueing rule
   `n=ceil(demand/(0.85·rate))` every 5 sim-min, overload-first budget,
   `set_management()` seeds baselines), Extra pick slots (+1 slot per
   station; S5's goes ABOVE), Balanced zoning (equal same-side location
   budgets — see open questions), plus the pre-existing
   ETA/global/slotting toggles. Panel also has a "→ L16·R50" optimum
   button (stale — see below) and scrolls with the wheel.
3. **Graph/strip** — session-continuous LINES/HR graph (offsets survive
   all rebuilds), grey warm-up (`metrics.EQUILIBRIUM_SECONDS=2700`,
   measured: rolling rate hits ~90% steady at 40–45 sim-min), flat
   settled-average lines labelled per state (`ø381 · sequential`),
   staggered yellow event markers, pink rolling mean-walk-time line
   (2nd axis), time axis, location spectrum (picks over the 2000
   locations), station backlog/cap/pickers chart (sticky axes,
   constraint station red), big total-picker number. Window 1332×780,
   RESIZABLE|SCALED (aspect locked).
4. **Model decisions (user-set, do not revert)**: demand is FLAT across
   all 2000 SKUs (`sku_weight()==1.0`; order book self-regenerates via
   metadata stamp — `data/order_book.json` committed); south-only picker
   detour; line==pick; walk calibration FROZEN (μ30s σ10s).

## Key experiment results (results/*.md in this worktree)
- `results/highway_sweep.md` — pillar sweep found L16/R50 = 26.8 o/hr
  vs 11.0 default. **CAVEAT: run under OLD popularity demand AND rows
  L≥31 were poisoned by the since-fixed depot-gridlock bug.** Stale.
- `results/slots_mgmt_ab.md` — 2×2 factorial (old demand): picker mgmt
  dominates (+22 o/hr at classic layout); extra slots worthless alone,
  +4.9 on top of mgmt; classic(23,52)+both BEAT L16/R50+both (42.0 vs
  38.8) → layout optima are CONDITIONAL on staffing policy.
- Flat-demand runs (2h seed 42): baseline 23.0 o/hr; mgmt+extra 39.5
  (S7 still 100% fill, 18 pickers); mgmt+extra+R→62 34.5 (S7 40%);
  mgmt+extra+balanced-zoning 34.5. Baseline 8.6h GUI soak: 20.6 o/hr,
  62-min cycles, 707 waiting_for_station stucks (up to 4.5h waits).

## OPEN QUESTIONS / NEXT QUEUE (in priority order)
1. **The real constraint under flat demand is STATIONS-PER-ORDER, not
   zone balance.** 20 uniform lines ⇒ an order needs S7 with ~97%
   probability even under balanced zoning (336-SKU zone) — that's why
   balanced zoning's first A/B was NEGATIVE (34.5 vs 39.5). Levers to
   investigate: fewer/bigger zones per side, order batching by zone,
   splitting orders across carts, or sequencing carts to visit fewer
   stations. THIS is the frontier toward the 2000–3000 picks/hr target
   (best so far ~950 picks/hr; picker busy only ~50%, 60–76
   lines/picker/hr vs 240 target).
2. **Re-run the pillar sweep** under flat demand + mgmt + extra slots
   (`experiments/run_highway_sweep.py` — update it to pass the new
   kwargs). The old optimum is stale; update `layout.OPTIMAL_HIGHWAY`
   + the panel button + CLAUDE.md note from the result.
3. **Refresh `constants.OPTIMAL_FLEET`** (fleet targets per strategy
   combo) — tuned pre-flat-demand; the strategy toggles retarget the
   fleet with stale numbers.
4. Dynamic-pool economics changed (south detour ≈ 85 m S1↔S9 one-way,
   was ~55): re-A/B dynamic vs static under mgmt. Relocation policy is
   still maximally eager (herding, ~1 move/2 picks) — threshold/
   worth-the-walk/cooldown hysteresis is designed but NOT implemented
   (see conversation notes in git log bf20817..73007ff era).
5. `EXPERIMENT_DESIGN.md` still references deleted `velocity` slotting.

## Gotchas for the next session
- `run_headless` resets the layout singleton per call; in-process
  parallelism is UNSAFE (module singletons) — use worker processes
  (see experiments/run_slots_mgmt_ab.py).
- Sweeps: `export=False` or you spam results/sim_results.md.
- After ANY world-geometry change re-verify the default map against
  the golden invariants (tests do this) — and stress the parameter
  EXTREMES; golden-diff only proves the default (see tasks/lessons.md).
- tasks/dynamic-highway-plan.md has the original design + review notes.
# ⚡ SESSION HANDOFF — read this first (2026-07-14, updated evening session)

## ⚡ Slotting session update (2026-07-14, parallel session — slotting owner)
User-set slotting spec now implemented (all committed this session):
- **3 strategies only**: sequential / aisle_proximal / fibonacci. **`velocity`
  DELETED at user request** — EXPERIMENT_DESIGN.md still references it at
  lines ~60/87/158 and needs updating (its owner: experiments session).
- **`aisle_proximal` semantics per user spec**: within each (aisle, station)
  subgroup, most popular SKU nearest that station's (highway) end; aisles
  with a station at either end split in two, least popular meets in the
  middle. Same sort key as before (own-station walk) + deterministic index
  tiebreak; docstrings now state the user-facing meaning. Old 17.0 m figure
  stale; current demand-weighted walks: sequential 18.1 m, aisle_proximal
  18.0 m, fibonacci 18.8 m.
- **GUI**: "Slotting:" panel row is clickable — cycles the 3 arms and does a
  FULL world restart (`_build_world()` in __main__.py: ID-counter reset +
  re-seed 42 → identical order stream per arm). Throughput strip is now a
  per-slotting **picks/hr** comparison graph (rolling 15 min, t=0-aligned,
  finished runs dimmed; `agv_simulation/metrics.py::rolling_rate`).
  Light-grey SKU numbers drawn at rack slots (hotter of the 2 levels per
  face) so placement is visually verifiable per arm.
- Tests: +12 (tests/test_slotting.py, tests/test_metrics.py); 76 green.
- 1h seed-42 headless smoke: sequential 13.0 o/hr, aisle_proximal 15.0,
  fibonacci 12.0 (all picker_busy 52%, picks/hr 413–440).

## ⚡ Evening update (through commit 2e7231f)
Model changes (all user-set): orders N(20,9) lines in SKU space (F1
fairness implemented), BOX_DEPOT_TIME 60 s, **side-constrained zoning**
(pickers can't cross the highway; west S1/S3, central S2/S4/S6/S8, east
S5/S7/S9). Terminology canonical: line = SKU on an order, line == pick.
Headline (8h seed 42, 10A/25C): sequential 11.7 o/hr vs velocity 32.3
(+176%) — walk AND zone balance (S3 99% busy vs S5 2% under sequential).
Dispatch (ETA/HUN) neutral until layout balanced. Stakeholder 2-pager:
`results/2pager_2026-07-14.md`. GUI: 13"-fit (1332×560), zone-colored
stations (no legend), toggles auto-retarget fleet (OPTIMAL_FLEET
provisional; screen results → results/runs/fleet_screen_2026-07-14.json).
Old pre-2026-07-14 results NOT comparable. Cleanup deferred by user.
Next: picker strategies (static vs dynamic-within-side), sweep, matrix.

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
- [x] **Placement visualization** — DONE (2026-07-14):
      `experiments/plot_placement.py` → `results/figures/` (PNGs gitignored,
      regenerable): 2×2 popularity maps per slotting (velocity's hot-SKU
      pull toward stations and fibonacci's track-edge rings both visible) +
      walk-time bar chart (velocity 13.1 m/22 s ... fibonacci 18.0 m/29 s).
      GUI now shows "Slotting: <name>" under STRATEGIES; stale
      "picks/cart-visit μ4 σ2" overlay label replaced with
      "lines/order: μ20 σ9". Verified via SDL dummy snapshot.
- [x] **Station/aisle zone color-coding (user request)** — DONE (2026-07-14):
      `Catalog.zone_border_segments()` (geometric — identical across
      slottings) + renderer `ZONE_COLORS`/`draw_zone_borders`/legend.
      N face = run's top edge, S face = bottom edge, split faces segmented;
      S-station tiles outlined in their zone color; ZONES legend top-left.
      Verified via SDL snapshot.
- [x] **Picker strategies as experiment toggles (user request)** — DONE
      (2026-07-14 evening): `PickerManager(strategy='static'|'dynamic')`;
      dynamic = idle picker relocates to the worst backlog on ITS OWN SIDE
      (never crosses the highway), inter-station walk is real time and
      counts busy; stats add relocations/relocation_seconds; stats
      attribute to the picker's current station.
      `run_headless(picker_strategy=...)` + GUI "Dynamic pickers" toggle
      (STRATEGIES panel; picker overlay shows the mode). 4 new tests
      (64 green). Experiment matrix §A2 added to EXPERIMENT_DESIGN.md.
      NO experiment runs yet — user said hold headless runs until told.
- [x] **Integration sweep** — DONE: 6 combos × 8h seed-42, all gates clean
      (results/runs/integration_sweep.json).
- [x] **Cleanup (subagents)** — DONE (commit 3278a9d): dead code removed
      (CART_SPAWN, sample_zone_skus), dispatcher hot-path candidate lists
      (bit-identical verified), 7 edge-case tests. Deferred: _reserved_tiles
      memoization, cart_start_times leak on retirement.
- [x] **Run experiments + findings doc** — DONE (commit 4ceab36): 40-run
      matrix, `results/FINDINGS_2026-07-14.md`. Decisions: ADOPT fibonacci
      slotting (+49%; mechanism = zone BALANCE not walk distance) + dynamic
      pickers (+30%; winner 32.4 o/hr = 1.94× baseline); REJECT dispatch
      strategies (ETA +1.6% below bar; Hungarian tail-risk: one seed 9.9).
      Next frontier: staffing hot stations, more AGVs (winner is 80%
      AGV-utilized), shorter pick cycles toward 240 lines/picker/hr.

Multi-session warning: another Claude session may share this working tree
and branch — check `git status` for foreign changes before editing/committing;
stage only files whose diff is yours (see memory: concurrent-sessions-same-worktree).

⚠️ SESSION OWNERSHIP (2026-07-14 evening, per user): **slotting strategies
are owned by another session** — this session must not edit the slotting
assignment code (`aisles.py` `_assign_*` / SLOTTING_STRATEGIES surface) or
slotting-specific docs/figures while that work is in flight. This session
owns pickers/dispatcher/GUI. Headless experiment runs are ON HOLD until
the user says go (applies to both sessions' sweeps).

📖 FOR THE SLOTTING SESSION — canonical order book (user spec, later
2026-07-14): demand is now a FIXED pregenerated list, 15 h × 3,000
lines/hr (2,243 orders / 45,007 lines; sizes N(20,9); half-normal product
frequency), generated deterministically (orderbook.py, BOOK_SEED) and
committed at `data/order_book.json`. **Empirical SKU counts — "the most
commonly occurring" — are at `data/order_book_frequencies.json`** (or
`orderbook.sku_frequencies(ensure_order_book())`): aisle_proximal &
friends should rank by THESE counts rather than the analytic sku_weight
curve. Orders consume the book by default in both headless
(`order_book=True`) and the GUI; seeds are window offsets into the book
(paired across arms, varying across seeds).

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
