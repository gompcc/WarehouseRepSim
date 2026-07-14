# Experiment matrix — 40 runs (8h, 10A/25C, order book, seeds [11, 42, 77, 101, 137])

| Arm (slotting/pickers/dispatch) | Steady o/hr (min–max) | Picks/hr | Lines/picker/hr | Busy | Busy CV | AGV util | Validity |
|---|---|---|---|---|---|---|---|
| aisle_proximal/static/baseline | **16.8** (15.7–17.6) | 341 | 37.8 | 29% | 0.98 | 40% | OK |
| fibonacci/dynamic/baseline | **32.4** (31.6–33.5) | 636 | 70.7 | 66% | 0.69 | 80% | OK |
| fibonacci/static/baseline | **24.9** (23.6–25.5) | 491 | 54.5 | 45% | 0.78 | 61% | OK |
| fibonacci/static/eta_reservations | **25.3** (24.0–26.0) | 495 | 55.0 | 45% | 0.78 | 59% | OK |
| fibonacci/static/eta_reservations+global_assignment | **25.3** (24.0–26.5) | 496 | 55.1 | 45% | 0.78 | 60% | OK |
| fibonacci/static/global_assignment | **21.9** (9.9–26.1) | 436 | 48.5 | 40% | 0.78 | 63% | OK |
| sequential/dynamic/baseline | **21.3** (19.3–22.4) | 419 | 46.6 | 42% | 0.85 | 59% | OK |
| sequential/static/baseline | **16.7** (15.5–17.2) | 338 | 37.6 | 29% | 0.98 | 38% | OK |
