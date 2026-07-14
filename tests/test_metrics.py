"""Rolling picks/hr math (agv_simulation.metrics)."""

from agv_simulation.metrics import rolling_rate


def test_empty_series():
    assert rolling_rate([]) == []


def test_constant_rate_full_window():
    # 1 pick every 10s from t=0: cumulative at t is t/10 -> 360/hr everywhere
    samples = [(t, t / 10.0) for t in range(0, 3600, 60)]
    rates = rolling_rate(samples, window=900.0)
    assert len(rates) == len(samples)
    # skip t=0 (zero span); all later points must be exactly 360/hr
    for t, r in rates[1:]:
        assert abs(r - 360.0) < 1e-6, (t, r)


def test_pre_window_divides_by_elapsed():
    # 60 picks happen in the first 60s, then nothing.
    samples = [(0.0, 0.0), (60.0, 60.0), (300.0, 60.0)]
    rates = dict(rolling_rate(samples, window=900.0))
    # at t=60: 60 picks / 60s = 3600/hr
    assert abs(rates[60.0] - 3600.0) < 1e-6
    # at t=300 (window still underflowing): 60 picks / 300s = 720/hr
    assert abs(rates[300.0] - 720.0) < 1e-6


def test_burst_leaves_window():
    # burst of 90 picks at the start; after the 900s window passes, rate -> 0
    samples = [(0.0, 0.0), (10.0, 90.0)] + [(float(t), 90.0) for t in range(600, 2400, 600)]
    rates = dict(rolling_rate(samples, window=900.0))
    assert rates[1800.0] < rates[600.0]
    assert abs(rates[1800.0]) < 1e-6


def test_zero_time_guard():
    assert rolling_rate([(0.0, 5.0)]) == [(0.0, 0.0)]
