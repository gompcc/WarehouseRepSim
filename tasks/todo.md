# Environment/Dispatcher Separation + Stuck-Cart Bug Hunt (2026-07-14)

Goal: stable, realistic environment cleanly separated from the dispatcher policy;
robust structured logging; find & fix where carts get stuck; optimize throughput.

Baseline (this session, pre-change): 10 AGVs / 25 carts / 8h → **43.4 orders/hr**,
avg_cycle 1099s (only 13 samples — metrics bug), blocked 9.3%.

## Phase 1 — Environment layer + robust logging
- [x] Create `agv_simulation/environment.py` with `Environment` class:
      owns tiles/graph/agvs/carts, cart spawning, `step(dt)` (AGV + cart updates),
      and a structured `EventLog` (JSONL-able event stream + counters)
- [x] Stuck-cart watchdog in Environment: cart with no lifecycle progress for
      N sim-seconds → warning event + per-cart stuck stats
- [x] Physics guard: cart position may only change while carried by an AGV
      (detects teleports) — environment audits realism
- [x] Refactor `headless.py` to drive `Environment` (same placement/spawn cadence)
- [x] Refactor `__main__.py` to drive `Environment` (GUI keeps interaction code)

## Phase 2 — Diagnose at speed (headless ≈ 1300x real time)
- [x] Run instrumented sim → found: 4/25 carts permanently dead (orphaned in
      WAITING_FOR_STATION with no order), 485 stuck events, cycle metric broken

## Phase 3 — Bug fixes (validated against stuck report)
- [x] Orphaned-cart deadlock: WAITING cart with `order=None` matched no dispatch
      branch → re-route to Box Depot (`_create_jobs`)
- [x] Cycle-time metric: stamp start on every order cycle, not just cart's first
- [x] Teleport on give-up: release cart at AGV's actual position; NEVER drop on
      highway tiles (abandoned cart gridlocks the one-way loop)
- [x] Double pack-off: `Order.packed` flag routes aborted returns home
- [x] Retarget hair-trigger: failed retargets now spaced out (were burning all
      3 attempts in 0.3s of the same congestion)
- [x] `_find_buffer_spot` excludes AGV-occupied tiles (parked AGV made target
      unreachable → retarget thrash)
- [x] ENVIRONMENT: head-on deadlock 2-cycle at junction (9,7)↔(8,7) removed —
      froze entire warehouse when two AGVs met (seed-0 repro, 18 min in)
- [x] ENVIRONMENT: row 8 cols 1-8 dead-end trap at (1,8) — added merge-north
      edges; graph now sink-free and fully mutually reachable (verified)

## Phase 4 — Verification
- [x] pytest suite green (29 tests, incl. 3 new regression tests)
- [ ] 12-seed deadlock hunt clean at 10/25
- [ ] A/B headless runs (10/25 and 14/25) vs baseline; compare orders/hr,
      stuck stats, thrash counts (interim: 14/25 hit 77.7-80.2/hr vs record 62)
- [ ] Update tasks/lessons.md + results/sim_results.md with iteration entry

## Review
(to fill in when done)
