"""Pure metric helpers shared by the GUI main loop and the renderer.

No pygame, no sim imports — keeps the math testable and avoids an import
cycle (__main__ -> renderer -> metrics).
"""

from __future__ import annotations

from bisect import bisect_left

# Trailing window for rolling rates (sim-seconds). Matches the 15-min
# window the throughput strip has always used.
ROLLING_WINDOW = 900.0


def rolling_rate(
    samples: list[tuple[float, float]],
    window: float = ROLLING_WINDOW,
) -> list[tuple[float, float]]:
    """Rolling per-hour rate from cumulative-count samples.

    ``samples`` is a chronological list of ``(sim_t, cumulative_count)``.
    Returns one ``(sim_t, count_per_hour)`` point per input sample, where
    the rate at t covers the trailing ``window`` seconds. Before a full
    window has elapsed the denominator is t itself, so early rates reflect
    the true average instead of overshooting.
    """
    if not samples:
        return []
    times = [t for t, _ in samples]
    out: list[tuple[float, float]] = []
    for t, count in samples:
        t0 = t - window
        if t0 <= times[0]:
            base_count = samples[0][1]
            span = t - times[0] if t > times[0] else 0.0
            span = max(span, t)  # from sim start when the window underflows
        else:
            i = bisect_left(times, t0)
            # interpolate the cumulative count at exactly t0
            t_lo, c_lo = samples[i - 1]
            t_hi, c_hi = samples[i]
            frac = (t0 - t_lo) / (t_hi - t_lo) if t_hi > t_lo else 0.0
            base_count = c_lo + frac * (c_hi - c_lo)
            span = window
        rate = (count - base_count) / span * 3600.0 if span > 0 else 0.0
        out.append((t, max(rate, 0.0)))
    return out
