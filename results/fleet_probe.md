
## Fleet probe — 2026-07-29 15:59

L25/R68, mgmt + extra slots + batched release, flat demand, 2.0h sims. Screen seed 42; confirm top 3 x seeds (41, 42, 43).

### Screen (seed 42)

| AGVs | carts | orders/hr | picks/hr | util | blocked |
|------|-------|-----------|----------|------|--------|
| 18 | 30 | 91.5 | 1984 | 54% | 3% |
| 18 | 25 | 89.5 | 1910 | 48% | 1% |
| 14 | 30 | 88.5 | 1862 | 74% | 3% |
| 16 | 30 | 87.0 | 1862 | 64% | 4% |
| 16 | 35 | 87.0 | 1922 | 68% | 5% |
| 16 | 25 | 86.0 | 1806 | 53% | 1% |
| 14 | 25 | 84.5 | 1792 | 68% | 2% |
| 14 | 35 | 80.0 | 1766 | 79% | 5% |
| 18 | 35 | 77.5 | 1698 | 62% | 8% |
| 12 | 25 | 71.0 | 1536 | 82% | 2% |
| 12 | 30 | 71.0 | 1562 | 89% | 4% |
| 10 | 25 | 62.5 | 1367 | 91% | 3% |
| 12 | 35 | 59.5 | 1390 | 91% | 7% |
| 10 | 30 | 57.0 | 1325 | 94% | 5% |
| 10 | 35 | 48.5 | 1157 | 95% | 7% |

### Confirmed (mean over seeds)

| AGVs | carts | orders/hr mean | min-max | picks/hr |
|------|-------|----------------|---------|----------|
| 18 | 30 | 93.3 | 91.5-94.5 | 1992 |
| 18 | 25 | 86.8 | 83.5-89.5 | 1852 |
| 14 | 30 | 82.7 | 78.5-88.5 | 1774 |

### Grid-edge check (18A won the grid, so probe past it; 2h seed 42)

| AGVs | carts | orders/hr | picks/hr | util | blocked |
|------|-------|-----------|----------|------|--------|
| 20 | 30 | 93.5 | 2029 | 47% | 2% |
| 22 | 30 | 94.5 | 2032 | 43% | 2% |
| 20 | 35 | 89.5 | 1968 | 54% | 4% |

Throughput plateaus ~93-94 o/hr / ~2030 picks/hr past 18 AGVs while
utilization slides toward 40% — adding AGVs no longer buys throughput,
so the binding constraint has moved off transport (candidate: the
MANAGE_MAX_TOTAL=30 picker cap — ~26 busy-equivalent pickers are needed
at this rate with 39s side-wide walks; also check station cart slots).
**18A/30C is the economic optimum** (+4 AGVs past it buys +1 o/hr).
`constants.OPTIMAL_FLEET[(False, False)]` updated to (18, 30).
