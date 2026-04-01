# Dispatcher Optimization Log

## Current Record
- **Peak throughput**: 38.0 orders/hr
- **Config**: 12 AGVs, 20 carts, 7200s duration
- **Date**: 2026-03-31
- **Baseline commit**: e78e46c (Fix highway congestion bugs causing gridlock under high AGV counts)

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
