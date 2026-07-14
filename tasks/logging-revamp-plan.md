# Logging & results-storage revamp — implementation plan (assessed 2026-07-14)

Verdict from the read-only assessment agent: **per-tick logs are NOT needed.**
The waste is (a) `EventLog.events` — every cart_spawned/agv_spawned/cart_state
dict kept in memory forever (~20–40 MB per 8h run) and never read
programmatically (stuck_report reads only counters/accumulators; no entry
point ever passes event_jsonl), and (b) ~18 dispatcher lifecycle
`logger.info` lines (~1 MB/8h) consumed by no one (experiments run at ERROR).

One-pass implementation (files: environment.py, headless.py, dispatcher.py):

1. **environment.py `EventLog.record`**: add class attr
   `KEEP_IN_MEMORY = {"stuck", "teleport"}`. Always bump counters and write
   JSONL if enabled; append to `self.events` only if
   `kind in KEEP_IN_MEMORY or self._jsonl`. stuck_report() unaffected.
2. **headless.py snapshots**: param `snapshot_interval: float = 60.0`;
   in-loop, append `{t, completed, active_agvs, blocked_agvs, waiting_carts,
   stuck_cum, fill}` every interval; add `"snapshots"` to return dict
   (~480 rows/8h — real throughput time series for graphs & experiments,
   works headless unlike the GUI strip).
3. **dispatcher.py**: demote the 18 lifecycle `logger.info` →
   `logger.debug` (in _create_jobs/_progress_jobs/_complete_job/
   _assign_jobs/_handle_blocked_agvs/_park_idle_agvs); keep the 4
   `logger.warning`. environment.py: demote the 2 spawn INFO → DEBUG; keep
   STUCK/PHYSICS VIOLATION warnings.
4. **headless.py per-run JSON (optional)**: param `results_json: str | None`;
   dump `{metadata, summary, stuck_report, snapshots}` to
   `results/runs/<timestamp>.json`. Keep markdown export untouched.
   Long-term: experiments compare N JSON files instead of parsing
   sim_results.md (6,700+ lines, append-forever).

Also from EXPERIMENT_DESIGN.md instrumentation needs: add
`order_completion_times` to the run_headless return dict (warm-up
exclusion) and per-station picker stats (~10 LOC in picker.py).
