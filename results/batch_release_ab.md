# Zone-batched order release A/B — 2026-07-29

The stations-per-order lever (next-queue #1; 2-pager recommendation #4).
Under flat demand a 20-line order touched ~7 of 9 stations — every cart
toured most of the warehouse, and balancing zone SIZES couldn't change
that (balanced zoning A/B was negative). Batched release re-buckets at
order creation: ALL of an order's lines on a side go to ONE same-side
station (rotated by order id so load spreads across each side's
stations), cutting stops to ≤3. Pickers legally roam their whole side —
the longer cross-zone walks are priced by the frozen walk calibration,
and management's service-rate estimate prices the side-wide pool
(`Catalog._pick_pool`).

Method: 2h sims, seeds 41/42/43 (paired order-book windows), 10 AGVs /
25 carts, sequential slotting, baseline dispatch, `export=False`.
Implemented in commit 96f3e9f; toggle `run_headless(batch_release=True)`
/ GUI "Batched release (1 stop/side)".

## Headline: +57%, ranges disjoint, station saturation gone

| Arm (2h, 10A/25C)     | s41  | s42  | s43  | mean | picks/hr | st/ord |
|------------------------|------|------|------|------|----------|--------|
| mgmt + extra (baseline)| 32.5 | 39.5 | 34.5 | 35.5 | ~820     | 6.99   |
| mgmt + extra + **batch** | 53.5 | 57.5 | 56.5 | **55.8** | **~1220** | 2.91 |
| batch alone            |  —   | 24.5 |  —   |  —   | 560      | 2.91   |

- Worst batched seed (53.5) beats best baseline seed (39.5) by 14 o/hr.
- **picks/hr ~1220 is the new best under flat demand** (prior best ~950;
  target 2000–3000). Cycle time 32.5 → 22.6 min (seed 42).
- Station fill at end of run: baseline had S2/S3/S7 pegged at 100%;
  batched max is 0.6 — **the station-saturation ceiling is broken**.
- Batch alone (no mgmt) is only +1.5 o/hr over the 23.0 baseline: fixed
  1-picker crews saturate the east stations once each serves a
  side-wide pool. Batching NEEDS management staffing — pair them.

## Mechanism & costs (seed 42)

- stations/order 6.99 → 2.91 (measured; new `avg_stations_per_order`
  result field). Fewer stops = fewer transport legs + fewer station
  queue entries per order.
- Priced trade-off: mean pick walk 29.8 s → 39.3 s (+32%) — pickers
  fetch side-wide. Management absorbs it (65 hires vs 30 over 2h);
  lines/picker/hr 48 → 50 (still far off the 240 target — pickers are
  only 54% busy because the constraint moved).
- **Constraint is now AGV transport**: agv_util 0.88–0.96, blocked
  3–7%, no station saturated, pickers half-idle. Fleet re-optimization
  (queue #3) is the natural next lever; the 10-AGV default was tuned
  for a station-bound regime.

## Caveats

- Rotation (`order_id % n_side_stations`) is demand-blind; it's right
  for flat demand but should be revisited if demand skew returns
  (walk-optimal or fill-aware choice then becomes attractive).
- Balanced zoning is a no-op under batching (assignment is side-based,
  zones only affect the map overlay + off-toggle behavior).
- MANAGE_MAX_TOTAL=30 concurrent pickers did not bind at 2h/55 o/hr,
  but will at higher throughput with 39 s walks (~2000 lines/hr needs
  ~26 busy pickers) — watch it in fleet sweeps.
