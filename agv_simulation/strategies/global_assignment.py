"""Globally optimal AGV↔job matching (Hungarian algorithm).

Baseline assignment is greedy: it walks the priority-sorted job list and
gives each job the nearest free AGV. Greedy matching is order-dependent —
job A can take the only AGV near job B, forcing B's AGV to cross the
warehouse, even when swapping both assignments is cheaper in total.

This module solves the full bipartite assignment problem over *all* free
AGVs × *all* pending jobs each tick (pure-python O(n³) Hungarian; matrices
here are at most ~16×30, microseconds). Lifecycle priority is preserved as a
cost bias rather than a hard sort, so a completion-path job still wins a
contested AGV, but not at the price of an absurdly long fetch.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..enums import AGVState

if TYPE_CHECKING:
    from ..agv import AGV
    from ..models import Job

logger = logging.getLogger(__name__)

INF = float("inf")

# Cost (in tiles) added per priority level — one level ≈ 40 tiles of fetch
# distance, so lifecycle ordering dominates unless the detour is extreme.
PRIORITY_SCALE = 40.0
# Soft penalty for AGVs that already failed this job (baseline skips them).
FAILED_PENALTY = 5000.0


def min_cost_assignment(cost: list[list[float]]) -> list[tuple[int, int]]:
    """Solve the rectangular assignment problem; return matched (row, col) pairs.

    Standard Hungarian algorithm with potentials, O(rows²·cols).
    """
    transposed = False
    n, m = len(cost), len(cost[0])
    if n > m:
        cost = [list(col) for col in zip(*cost)]
        n, m = m, n
        transposed = True

    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)      # p[j] = row matched to column j (1-indexed)
    way = [0] * (m + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    pairs = [(p[j] - 1, j - 1) for j in range(1, m + 1) if p[j]]
    if transposed:
        pairs = [(c, r) for r, c in pairs]
    return pairs


class GlobalAssignment:
    """Hungarian AGV↔job matcher (toggle: ``global_assignment``)."""

    def assign(
        self,
        dispatcher,
        agvs: list[AGV],
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        tiles: dict,
        slots: int,
    ) -> None:
        """Match free AGVs to pending jobs globally; dispatch up to *slots*."""
        free_agvs = [
            a for a in agvs
            if a.state == AGVState.IDLE
            and a.current_job is None
            and a.carrying_cart is None
        ]
        jobs: list[Job] = list(dispatcher.pending_jobs)
        if not free_agvs or not jobs or slots <= 0:
            return

        cost: list[list[float]] = []
        for agv in free_agvs:
            row: list[float] = []
            for job in jobs:
                dist = (
                    abs(agv.pos[0] - job.cart.pos[0])
                    + abs(agv.pos[1] - job.cart.pos[1])
                )
                prio = dispatcher._JOB_PRIORITY.get(job.job_type, 99)
                c = dist + prio * PRIORITY_SCALE
                if agv.agv_id in job.failed_agvs:
                    c += FAILED_PENALTY
                row.append(c)
            cost.append(row)

        pairs = min_cost_assignment(cost)
        pairs.sort(key=lambda rc: cost[rc[0]][rc[1]])

        assigned: list[Job] = []
        for r, c in pairs:
            if len(assigned) >= slots:
                break
            agv, job = free_agvs[r], jobs[c]
            blocked = {
                a.pos for a in agvs if a is not agv and a.state != AGVState.IDLE
            }
            if agv.pickup_cart(job.cart, graph, tiles, blocked=blocked):
                job.assigned_agv = agv
                agv.current_job = job
                dispatcher.active_jobs.append(job)
                assigned.append(job)
                logger.info(
                    "[Hungarian] AGV %d assigned Job #%d (%s) → pickup C%d cost=%.0f",
                    agv.agv_id, job.job_id, job.job_type.value,
                    job.cart.cart_id, cost[r][c],
                )
        for job in assigned:
            dispatcher.pending_jobs.remove(job)
