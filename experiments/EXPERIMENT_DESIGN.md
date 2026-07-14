# Experiment Design — Slotting & Dispatch Study

Goal: a MAX two-page findings doc with two sections — (A) product layout
(SKU slotting) and (B) dispatcher strategies — answering one question:
**what configuration maximizes picks/hr (and orders/hr)?** Business target
context: 2,000–3,000 picks/hr; throughput is the decision metric.

Diagnosis that shapes everything below: at the default operating point
(10 AGVs / 25 carts) the system is **picker/station-bound**, not
transport-bound (recent baseline: pickers 81% busy, AGVs ~20% active,
S2 fill 100%, blocked ~0%). So slotting (walk time per pick) attacks the
binding constraint directly; dispatch strategies mostly help by keeping
pickers fed and balanced, not by moving AGVs faster.

---

## 0. Prerequisite instrumentation (tiny, do before any runs)

1. **Expose completion timestamps.** `dispatcher.order_completion_times`
   already exists (`dispatcher.py:44,546`) but is not in the `run_headless`
   return dict (`headless.py:142-158`). Add one key:
   `"order_completion_times": list(dispatcher.order_completion_times)`.
   Enables warm-up exclusion without re-running anything.
2. **Per-station picker stats.** In `PickerManager.stats()` add
   `per_station: {sid: {picks_done, busy_fraction}}` (counters already
   tick per station in `update()`; ~10 LOC). Needed for the workload-balance
   figure (Fig 3).
3. **Fair order generation across slotting arms** — see Fairness rule F1.
   This is a required change to `Order.__init__` before Section A is valid.

All experiment runs use `export=False` (keep `results/sim_results.md` clean)
and `log_level="ERROR"`; write a dedicated
`results/slotting_study.md` / `results/dispatch_study.md` + a CSV of raw
per-run rows (arm, seed, config, metrics) for the figures.

---

## 1. Common design (both sections)

| Factor | Value | Rationale |
|---|---|---|
| Run length | 28,800 s (8 h), tick 0.1 s | Matches existing methodology; ~35–40 s wall each |
| Warm-up | Exclude first **1,800 s**: steady orders/hr = completions with t > 1800 / 7.5 h | Ramp-in (cart streaming + first loop) is ~20–30 min; timestamps from item 0.1. Picks/hr uses the full horizon (no timestamps) — bias is identical across arms and cancels in paired comparison; state this in the doc footnote |
| Seeds | **5 seeds: 11, 42, 77, 101, 137**, identical across all arms (paired) | 3 seeds was the house standard; 5 tightens the min–max band enough for 3% decisions |
| Fleet (primary) | 10 AGVs / 25 carts | Default, matches results history, picker-bound = realistic point |
| Fleet (secondary) | Section A: 14/25 (transport slack) · Section B: 10/15 (transport-bound, low WIP) | One robustness point each — enough to show whether rankings flip with the regime, without a full grid |
| Fixed | 1 picker/station, walk calibration (`WALK_TIME_FIXED=2.93`, `WALK_TIME_SCALE=1.0330`), `PICK_GRAB_TIME=10`, station capacities (`STATIONS`), depot 60 s (user-set 2026-07-14, was 45 s), packoff 20 s, spawn cadence (depot fill + 1 cart/5 s), `_PICKER_RNG_SEED` | Everything not under test is frozen |
| Decision rule | Adopt an arm iff paired mean Δ(primary metric) ≥ **+3%** vs its baseline AND the delta is positive on ≥ 4/5 seeds. Report mean [min–max], never a bare mean. | Guards against seed noise without heavyweight stats |
| Validity gate | `stuck_report.stuck_events == 0`, `teleport_events == 0`, `carts_left_early` not exploding vs baseline. A run failing the gate invalidates the arm until fixed — no averaging over broken runs. **Known issue (2026-07-14): the stuck watchdog flags carts legitimately queued in PICKING (~90–100 events/h at baseline) — exempt queued-for-picker carts from the watchdog before running, or the gate can never pass.** | Physics/deadlock bugs masquerade as policy effects |

Run budget: Section A = 4×5 + 4×3 = 32 runs; Section B = 8×5 + 3×5 = 55 runs;
+1 headline cell ×5 = ~92 runs ≈ 60 min wall at 8 parallel workers
(clone `experiments/run_strategy_comparison.py`'s `ProcessPoolExecutor` pattern).

---

## 2. Section A — product layout (slotting)

**Arms (4):** `sequential` (baseline), `aisle-proximal`, `fibonacci-rings`,
`velocity` — the 4 toggleable slotting strategies, with normal-distributed
SKU popularity active in **all** arms (popularity must not be a hidden
difference between arms).

**Matrix:** 4 strategies × 5 seeds at 10/25 (20 runs, decision set)
+ 4 strategies × 3 seeds (11, 42, 77) at 14/25 (12 runs, ranking-robustness
check only — one sentence in the doc: "ranking unchanged with transport slack"
or a caveat).

**Dispatcher fixed at baseline** (no toggles) for every Section A run —
slotting effects must not be laundered through a smarter dispatcher.

**Primary:** picks/hr (`picker_stats.picks_done / 8h`) and steady orders/hr.
**Mechanism metrics:** `walk_mean_s` (the required bar chart), walk m/pick
derived as `(walk_mean_s − 2.93) / 1.0330 × 1.4` (round-trip metres),
`busy_fraction`.
**Balance metrics:** per-station picks_done CV and max station `fill_rate`
(names the constraint station per arm).

---

## 3. Section B — dispatcher strategies

Run **under the Section A winner's slotting** (that is the layout you would
deploy; note it in the doc header). Arms, all at 10/25 × 5 seeds:

1. baseline
2. `eta_reservations`
3. `global_assignment`
4. `eta + hungarian`
5. `picker-aware dispatch` (new, §5.1)
6. `gated depot release` (new, §5.2)
7. `order-admission sequencing` (new, §5.3)
8. best-observed stack (winners of 2–7 combined; pick after singles are in)

Robustness: top-3 arms re-run at 10/15 × 5 seeds (dispatch matters most when
transport binds — if ETA/Hungarian only pay off there, the doc must say so).

Headline cell: best stack × best slotting vs baseline × sequential,
5 seeds — the single "adopt all of this and get +X%" number that opens the
2-pager.

**Primary:** steady orders/hr (and picks/hr as cross-check).
**Secondary:** avg cycle + p90 cycle (compute from returned `cycle_times`),
AGV utilization, picker `busy_fraction` (shows whether the bottleneck moved).

---

## 4. Metrics: report vs OMIT

Report (Section A): picks/hr, orders/hr, walk s/pick (+m/pick), picker busy %,
constraint station + max fill %.
Report (Section B): orders/hr, Δ% vs baseline, avg & p90 cycle (minutes),
AGV util %, picker busy %.

**OMIT from the 2-pager** (keep in the CSV only): `agv_blocked_fraction`,
full `station_fill` tables, `stuck_report` internals (it's a validity gate,
not a finding), `walk_sd_s`, `carts_served`/`carts_left_early`, wall-clock,
tick counts, full cycle-time histograms, per-seed tables. Every omitted
number is one the reader can't act on.

---

## 5. Fairness rules

- **F1 — Demand must be defined in SKU space, not station space.**
  **IMPLEMENTED 2026-07-14**: `Order.__init__` now draws
  `max(1, round(N(20, 9)))` distinct SKUs popularity-weighted from the
  global catalog (`Catalog.sample_skus`); the order-size distribution is
  user-set (mean 20 products/cart, SD 9 — replaces the old
  U(1,9) stations × N(4,2) lines mixture). The *stations visited* are
  derived from the active slotting's zoning. Slotting legitimately changing
  how many stations an order touches is an **effect to measure, not a
  confound to remove**. Verify with a checksum: for a given seed, order N's
  SKU multiset must be byte-identical across all 4 slotting arms (assert in
  the runner). NOTE: results predating this change are not comparable
  (order sizes and station-visit counts both shifted).
- **F2 — Never recalibrate walk time per arm.** `WALK_TIME_FIXED/SCALE` were
  fit to make the *baseline* geometry hit μ30/σ10. Re-fitting per slotting
  arm would erase the very effect under test. Freeze the constants; report
  each arm's realized `walk_mean_s` — the differences ARE the finding.
- **F3 — Same fleet, capacities, and processing times everywhere.** Station
  capacities are physical; if velocity slotting overloads one station, that
  imbalance is a real cost of that slotting — measure it (Fig 3), don't
  rebalance zones or capacities post hoc.
- **F4 — Paired seeds, single-variable arms.** Same 5 seeds in every arm;
  Section A varies only slotting (dispatcher = baseline), Section B varies
  only dispatch (slotting = fixed winner). Picker RNG is already an isolated
  stream (`_PICKER_RNG_SEED`) — do not touch.
- **F5 — Comparisons are within-seed deltas first**, then averaged. Report
  mean [min–max] of paired deltas, not differences of means.

---

## 6. New dispatcher strategies — critical evaluation

Recommended to implement (ranked):

**6.1 Picker-aware dispatch — IMPLEMENT FIRST (S/M cost, highest expected
payoff).** Mechanism: when `_choose_next_station`/`_pick_best_station`
scores candidate stations inside the travel window, score by **picker
backlog in SKU lines** (queued + in-service remaining, from
`PickerManager.queues` + `order.lines_remaining_at`) instead of cart-count
fill. Why it helps here: pickers are the bottleneck and fill-count is a bad
proxy — one cart with 8 lines occupies a picker longer than three carts with
1 line each; baseline shows S2 pinned at 100% while S8 idles at 25%.
Levelling picker utilization converts idle picker seconds directly into
picks/hr. Expected: **+5–15% picks/hr** at 10/25. Hooks already exist
(dispatcher holds `self.pickers`; ETA module shows the scoring pattern).

**6.2 Gated depot release (cart-release throttling) — IMPLEMENT (S cost,
modest but cheap).** Mechanism: hold a boxed cart at the depot until its
first station has a free slot *or* that station's picker backlog is below a
threshold; otherwise it launches, finds the station full, and gets buffered.
Critical note (Little's law): total WIP is already capped by `num_carts`, so
a static CONWIP cap ≈ just lowering the cart count, which the fleet sweep
already covers — the value here is only the **dynamic, destination-aware**
gate that trades depot dwell for eliminated buffer churn and blocked-AGV
time. Expected: **+0–5% orders/hr**, bigger cut in avg cycle and
`times_buffered`. If it shows <+3%, say so in the doc — a negative result on
a popular idea is a finding.

**6.3 Order-admission sequencing — IMPLEMENT (M cost).** Mechanism: the
depot holds a small backlog of k unassigned orders (k≈5) and binds to the
next free cart the order whose station set best *complements* current
station-level WIP (fills idle pickers, avoids the constraint station).
Why: attacks the same imbalance as 6.1 but at admission time, where the
choice is free — no extra travel is created. Expected: **+3–8% picks/hr**,
partially overlapping 6.1's gain (measure both alone before stacking).

**6.4 Order batching by station overlap — STRETCH ONLY (L cost, highest
ceiling).** Mechanism: bind 2 orders with overlapping station sets to one
cart; pickers pick both lists per visit. Why: halves cart-exchange overhead
per line (a station slot and picker gap is paid per *cart*, lines per visit
~4→~8) and halves loop traversals per order — directly relieves both
station-slot capacity and picker idle-between-carts. Expected: **+10–20%
orders/hr** — but it touches Order/Cart/Packoff semantics everywhere.
Do NOT block the 2-pager on it; list under "next steps" unless time allows.

Evaluated and REJECTED for this study:

- **Idle-AGV pre-positioning:** AGVs are ~20% active and blocked ~0% at the
  operating point — fetch latency is not binding, and `_park_idle_agvs`
  already spreads parking. Expected ≈ 0% at 10/25, maybe +2–4% at 10/15
  only. Not worth M cost now; revisit if the business point becomes
  transport-bound.
- **Priority aging:** in a closed, picker-bound system it reorders who waits
  but adds no picker capacity — expect ~0% throughput; it improves p95 cycle
  fairness only, and the user's stated metric is throughput. S cost but
  zero expected value on the decision metric. One line in "considered and
  excluded".

---

## 7. Figure plan (5 figures, all with mean ± seed min–max error bars)

| # | Figure | Axes / units | Decision it supports |
|---|---|---|---|
| 1 | **REQUIRED: bar — avg picker walk time by slotting strategy** (4 bars) | x: slotting arm; y: walk s/pick (secondary annotation: m/pick); reference line at 30 s calibrated baseline | Shows the *mechanism*: which slotting actually shortens walks, and by how many seconds of the ~40 s/line (30 walk + 10 grab) budget |
| 2 | Grouped bar — picks/hr and steady orders/hr by slotting (4×2 bars, or two aligned panels) | x: slotting arm; y-left: picks/hr; y-right: orders/hr; annotate Δ% vs sequential | The Section A verdict: does shorter walking convert to throughput (it can fail to, if station imbalance eats it — Fig 3 explains any gap) |
| 3 | Heatmap — per-station picker busy % (9 stations × 4 slotting arms) | x: S1–S9; y: slotting arm; cell: busy % (or picks share) | Exposes workload-balance side-effects of slotting; justifies why a walk-time winner might not be the throughput winner, and feeds the picker-aware-dispatch story |
| 4 | Bar — steady orders/hr by dispatcher arm at 10/25, baseline first, Δ% annotated; hatched overlay bars for the 10/15 robustness values on the top-3 arms | x: dispatcher arm; y: orders/hr | The Section B verdict incl. regime-dependence in one figure |
| 5 | Paired-dot / slope chart — headline: baseline×sequential vs best-stack×best-slotting, one dot pair per seed | x: two configs; y: steady orders/hr, per-seed lines | The adopt-this number, showing per-seed consistency rather than a bare average |

Not counted: the SKU placement visualization (exists separately; reference it,
one thumbnail max). Explicitly NOT included: cycle-time histograms, station
fill tables, AGV-utilization charts (numbers appear inline in Section B text).

---

## 8. Execution checklist

1. Instrumentation (§0) + F1 order-generation change; assert the F1 checksum.
2. Sanity: baseline × sequential, seed 42, must reproduce ~23 orders/hr at
   10/25 within seed noise (compare `results/sim_results.md` 2026-07-14
   entries) — if the F1 change moved the baseline, note the new reference
   level and re-anchor deltas to it.
3. Run Section A (32 runs, parallel) → pick slotting winner by picks/hr
   under the §1 decision rule; ties → prefer better station balance (Fig 3).
4. Implement 6.1, 6.2, 6.3 (each an isolated `StrategyConfig` toggle,
   baseline byte-identical when off — house rule).
5. Run Section B (55 runs) → pick stack → run headline cell (5 runs).
6. Validity gates on every run; regenerate all 5 figures from the CSV.
7. Write the 2-pager: Section A (Figs 1–3), Section B (Figs 4–5),
   "considered and excluded" one-liners, methods footnote (seeds, warm-up,
   decision rule) — everything else stays in the CSV.
