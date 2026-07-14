# Environment/Dispatcher Separation + Stuck-Cart Bug Hunt (2026-07-14)

Goal: stable, realistic environment cleanly separated from the dispatcher policy;
robust structured logging; find & fix where carts get stuck; optimize throughput.

Baseline (this session, pre-change): 10 AGVs / 25 carts / 8h → **43.4 orders/hr**,
avg_cycle 1099s (only 13 samples — metrics bug), blocked 9.3%.

## Phase 1 — Environment layer + robust logging
- [ ] Create `agv_simulation/environment.py` with `Environment` class:
      owns tiles/graph/agvs/carts, cart spawning, `step(dt)` (AGV + cart updates),
      and a structured `EventLog` (JSONL-able event stream + counters)
- [ ] Stuck-cart watchdog in Environment: cart with no lifecycle progress for
      N sim-seconds → warning event + per-cart stuck stats
- [ ] Physics guard: cart position may only change while carried by an AGV
      (detects/blocks teleports) — environment enforces realism
- [ ] Refactor `headless.py` to drive `Environment` (same placement/spawn cadence)
- [ ] Refactor `__main__.py` to drive `Environment` (GUI keeps interaction code)

## Phase 2 — Diagnose at speed (headless ≈ 1300x real time)
- [ ] Run instrumented sim; produce stuck report: where carts wait, thrash counts,
      blocked hotspots, job retry loops

## Phase 3 — Bug fixes (validate each against the stuck report)
- [ ] Cycle-time metric: stamp start on every order cycle, not just cart's first
- [ ] Teleport on give-up (`dispatcher.py` retarget cap): drop cart at AGV's
      actual position instead of teleporting to distant parking
- [ ] Double pack-off: cart dropped mid-RETURN re-enters MOVE_TO_PACKOFF because
      order completion isn't tracked — add `Order.packed` flag
- [ ] Buffer thrashing (C19 buffered 50x): hold-and-retry pathing briefly instead
      of instant buffer conversion; exclude AGV-occupied tiles from buffer targets
- [ ] Re-check `_find_buffer_spot`/dropoff target selection vs idle parked AGVs

## Phase 4 — Verification
- [ ] pytest suite green
- [ ] A/B headless runs (10/25 and 14/25) vs baseline; compare orders/hr,
      stuck stats, thrash counts
- [ ] Update tasks/lessons.md + results/sim_results.md with iteration entry

## Review
(to fill in when done)
