"""Dispatcher — orchestrates autonomous cart lifecycle."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .enums import AGVState, CartState, JobType, TileType
from .constants import (
    BOX_DEPOT_TIME, PICK_TIME_PER_ITEM, PACKOFF_TIME,
    BLOCK_TIMEOUT, REROUTE_COOLDOWN, JOB_CANCEL_TIMEOUT,
    MAX_CONCURRENT_DISPATCHES,
)
from .models import Job, Order, STATIONS

if TYPE_CHECKING:
    from .agv import AGV
    from .models import Cart, Tile

logger = logging.getLogger(__name__)


class Dispatcher:
    """Orchestrates the autonomous cart lifecycle through the warehouse."""

    def __init__(self, tiles: dict[tuple[int, int], Tile]) -> None:
        self._station_tiles: dict[tuple[str | None, TileType], list[tuple[int, int]]] = {}
        for (x, y), tile in tiles.items():
            key = (tile.station_id, tile.tile_type)
            if tile.station_id:
                self._station_tiles.setdefault(key, []).append((x, y))
        self.pending_jobs: list[Job] = []
        self.active_jobs: list[Job] = []
        self.completed_orders: int = 0
        self._station_fill_cache: dict = {}
        self.order_completion_times: list[float] = []
        self.cart_start_times: dict[int, float] = {}
        self.cycle_times: list[float] = []
        self._sim_elapsed: float = 0.0

    def _reserved_tiles(self, carts: list[Cart]) -> set[tuple[int, int]]:
        """Return set of tiles occupied by stationary carts or targeted by jobs."""
        reserved: set[tuple[int, int]] = set()
        for c in carts:
            if c.carried_by is None:
                reserved.add(c.pos)
        for job in self.pending_jobs:
            reserved.add(job.target_pos)
        for job in self.active_jobs:
            reserved.add(job.target_pos)
        return reserved

    def get_station_fill(
        self, carts: list[Cart]
    ) -> dict[str, tuple[int, int, float]]:
        """Return ``{station_id: (current, capacity, fill_rate)}`` for all stations."""
        reserved = self._reserved_tiles(carts)
        fill: dict[str, tuple[int, int, float]] = {}
        for station_id, capacity in STATIONS.items():
            key = (
                (station_id, TileType.PICK_STATION)
                if station_id.startswith("S")
                else (station_id, TileType.PARKING)
            )
            positions = self._station_tiles.get(key, [])
            current = sum(1 for pos in positions if pos in reserved)
            fill[station_id] = (current, capacity, current / capacity if capacity > 0 else 0.0)
        return fill

    def _pick_best_station(
        self,
        remaining_stations: list[int],
        cart_pos: tuple[int, int],
        carts: list[Cart],
    ) -> int | None:
        """Pick the least-busy station from *remaining_stations* using fill-rate tiers + distance."""
        fill = self.get_station_fill(carts)
        candidates: list[tuple[int, float, int]] = []
        for s in remaining_stations:
            sid = f"S{s}"
            current, capacity, rate = fill.get(sid, (0, 0, 1.0))
            if current >= capacity:
                continue
            priority = 1 if rate <= 0.50 else (2 if rate <= 0.75 else 3)
            station_tiles = self._station_tiles.get((sid, TileType.PICK_STATION), [])
            dist = (
                abs(cart_pos[0] - station_tiles[0][0]) + abs(cart_pos[1] - station_tiles[0][1])
                if station_tiles
                else float("inf")
            )
            candidates.append((priority, dist, s))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][2]

    def _find_tile(
        self,
        station_id: str,
        tile_type: TileType,
        carts: list[Cart] | None = None,
    ) -> tuple[int, int] | None:
        """Return an unoccupied tile for *station_id* + *tile_type*, or ``None`` if full."""
        key = (station_id, tile_type)
        positions = self._station_tiles.get(key, [])
        if not positions:
            return None
        if carts is not None:
            reserved = self._reserved_tiles(carts)
            for pos in positions:
                if pos not in reserved:
                    return pos
            return None
        return positions[0]

    def _find_buffer_spot(
        self,
        near_pos: tuple[int, int],
        carts: list[Cart],
        tiles: dict[tuple[int, int], Tile],
    ) -> tuple[int, int] | None:
        """Find the nearest unoccupied PARKING tile to use as a temporary buffer."""
        reserved = self._reserved_tiles(carts)
        best: tuple[int, int] | None = None
        best_dist = float("inf")
        for pos, tile in tiles.items():
            if tile.tile_type != TileType.PARKING:
                continue
            if tile.station_id is not None:
                continue  # skip station-associated parking (Box Depot, Pack-off)
            if pos in reserved:
                continue
            dist = abs(pos[0] - near_pos[0]) + abs(pos[1] - near_pos[1])
            if dist < best_dist:
                best_dist = dist
                best = pos
        return best

    def _has_job(self, cart: Cart) -> bool:
        """Check if *cart* already has a pending or active job."""
        for job in self.pending_jobs:
            if job.cart is cart:
                return True
        for job in self.active_jobs:
            if job.cart is cart:
                return True
        return False

    def _create_jobs(
        self,
        carts: list[Cart],
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        tiles: dict[tuple[int, int], Tile],
    ) -> None:
        """Check carts and create jobs as needed (capacity-based station routing)."""
        for cart in carts:
            if self._has_job(cart):
                continue

            if cart.state == CartState.SPAWNED and cart.carried_by is None:
                target = self._find_tile("Box_Depot", TileType.PARKING, carts)
                if target:
                    job = Job(JobType.PICKUP_TO_BOX_DEPOT, cart, target)
                    self.pending_jobs.append(job)
                    self.cart_start_times[cart.cart_id] = self._sim_elapsed

            elif cart.state == CartState.AT_BOX_DEPOT and cart.process_timer <= 0:
                if cart.order is None:
                    cart.order = Order()
                    logger.info(
                        "[Order #%d] Cart C%d: picks=%s, stations=%s",
                        cart.order.order_id, cart.cart_id,
                        cart.order.picks,
                        ["S" + str(s) for s in cart.order.stations_to_visit],
                    )
                remaining = [
                    s for s in cart.order.stations_to_visit
                    if s not in cart.order.completed_stations
                ]
                ns = self._pick_best_station(remaining, cart.pos, carts)
                if ns is None:
                    ns = cart.order.next_station()
                if ns is not None:
                    sid = f"S{ns}"
                    target = self._find_tile(sid, TileType.PICK_STATION, carts)
                    if target:
                        job = Job(JobType.MOVE_TO_PICK, cart, target, station_id=sid)
                        self.pending_jobs.append(job)

            elif cart.state == CartState.PICKING and cart.process_timer <= 0:
                if cart.order:
                    remaining = [
                        s for s in cart.order.stations_to_visit
                        if s not in cart.order.completed_stations
                    ]
                    ns = self._pick_best_station(remaining, cart.pos, carts)
                    if ns is None:
                        ns = cart.order.next_station()
                    if ns is not None:
                        sid = f"S{ns}"
                        target = self._find_tile(sid, TileType.PICK_STATION, carts)
                        if target:
                            job = Job(JobType.MOVE_TO_PICK, cart, target, station_id=sid)
                            self.pending_jobs.append(job)
                        else:
                            # Station full — buffer the cart to free this tile
                            buffer = self._find_buffer_spot(cart.pos, carts, tiles)
                            if buffer:
                                job = Job(JobType.MOVE_TO_BUFFER, cart, buffer)
                                self.pending_jobs.append(job)
                                logger.info(
                                    "[Dispatcher] C%d: station %s full, buffering to %s",
                                    cart.cart_id, sid, buffer,
                                )
                    elif cart.order.all_picked():
                        target = self._find_tile("Pack_off", TileType.PARKING, carts)
                        if target:
                            job = Job(JobType.MOVE_TO_PACKOFF, cart, target)
                            self.pending_jobs.append(job)
                        else:
                            # Pack-off full — buffer the cart to free this tile
                            buffer = self._find_buffer_spot(cart.pos, carts, tiles)
                            if buffer:
                                job = Job(JobType.MOVE_TO_BUFFER, cart, buffer)
                                self.pending_jobs.append(job)
                                logger.info(
                                    "[Dispatcher] C%d: Pack-off full, buffering to %s",
                                    cart.cart_id, buffer,
                                )

            elif cart.state == CartState.AT_PACKOFF and cart.process_timer <= 0:
                target = self._find_tile("Box_Depot", TileType.PARKING, carts)
                if target:
                    job = Job(JobType.RETURN_TO_BOX_DEPOT, cart, target)
                    self.pending_jobs.append(job)

            elif cart.state == CartState.WAITING_FOR_STATION and cart.carried_by is None:
                if cart.order:
                    remaining = [
                        s for s in cart.order.stations_to_visit
                        if s not in cart.order.completed_stations
                    ]
                    if remaining:
                        ns = self._pick_best_station(remaining, cart.pos, carts)
                        if ns is None:
                            ns = cart.order.next_station()
                        if ns is not None:
                            sid = f"S{ns}"
                            target = self._find_tile(sid, TileType.PICK_STATION, carts)
                            if target:
                                job = Job(JobType.MOVE_TO_PICK, cart, target, station_id=sid)
                                self.pending_jobs.append(job)
                    elif cart.order.all_picked():
                        target = self._find_tile("Pack_off", TileType.PARKING, carts)
                        if target:
                            job = Job(JobType.MOVE_TO_PACKOFF, cart, target)
                            self.pending_jobs.append(job)

            elif cart.state == CartState.COMPLETED and cart.carried_by is None:
                target = self._find_tile("Box_Depot", TileType.PARKING, carts)
                if target:
                    job = Job(JobType.RETURN_TO_BOX_DEPOT, cart, target)
                    self.pending_jobs.append(job)

    def _assign_jobs(
        self,
        agvs: list[AGV],
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        tiles: dict[tuple[int, int], Tile],
    ) -> None:
        """Assign pending jobs to free AGVs (capped to prevent highway gridlock)."""
        slots = MAX_CONCURRENT_DISPATCHES - len(self.active_jobs)
        if slots <= 0:
            return
        free_agvs = [
            a for a in agvs
            if a.state == AGVState.IDLE
            and a.current_job is None
            and a.carrying_cart is None
        ][:slots]
        assigned: list[Job] = []
        for job in self.pending_jobs:
            if not free_agvs:
                break
            best_agv = min(
                free_agvs,
                key=lambda a: abs(a.pos[0] - job.cart.pos[0]) + abs(a.pos[1] - job.cart.pos[1]),
            )
            dist = abs(best_agv.pos[0] - job.cart.pos[0]) + abs(best_agv.pos[1] - job.cart.pos[1])
            blocked = {a.pos for a in agvs if a is not best_agv}
            if best_agv.pickup_cart(job.cart, graph, tiles, blocked=blocked):
                job.assigned_agv = best_agv
                best_agv.current_job = job
                self.active_jobs.append(job)
                assigned.append(job)
                free_agvs.remove(best_agv)
                logger.info(
                    "[Dispatcher] AGV %d assigned Job #%d (%s) → pickup C%d dist=%d",
                    best_agv.agv_id, job.job_id, job.job_type.value,
                    job.cart.cart_id, dist,
                )
        for job in assigned:
            self.pending_jobs.remove(job)

    def _set_transit_state(self, job: Job) -> None:
        """Set the cart's transit state based on job type."""
        mapping = {
            JobType.PICKUP_TO_BOX_DEPOT: CartState.TO_BOX_DEPOT,
            JobType.MOVE_TO_PICK: CartState.IN_TRANSIT_TO_PICK,
            JobType.MOVE_TO_PACKOFF: CartState.IN_TRANSIT_TO_PACKOFF,
            JobType.RETURN_TO_BOX_DEPOT: CartState.TO_BOX_DEPOT,
            JobType.MOVE_TO_BUFFER: CartState.IN_TRANSIT,
        }
        job.cart.state = mapping.get(job.job_type, CartState.IN_TRANSIT)

    def _complete_job(self, job: Job) -> None:
        """Handle job completion after dropoff finishes."""
        cart = job.cart
        agv = job.assigned_agv

        if job.job_type == JobType.PICKUP_TO_BOX_DEPOT:
            cart.state = CartState.AT_BOX_DEPOT
            cart.process_timer = BOX_DEPOT_TIME
            logger.info(
                "[Dispatcher] C%d arrived at Box Depot — processing %ss",
                cart.cart_id, BOX_DEPOT_TIME,
            )

        elif job.job_type == JobType.MOVE_TO_PICK:
            station_num = int(job.station_id[1:])
            items = cart.order.items_at_station(station_num) if cart.order else 1
            cart.state = CartState.PICKING
            cart.process_timer = PICK_TIME_PER_ITEM * items
            if cart.order:
                cart.order.complete_station(station_num)
            logger.info(
                "[Dispatcher] C%d at %s — picking %d items (%ss)",
                cart.cart_id, job.station_id, items, cart.process_timer,
            )

        elif job.job_type == JobType.MOVE_TO_PACKOFF:
            cart.state = CartState.AT_PACKOFF
            cart.process_timer = PACKOFF_TIME
            logger.info(
                "[Dispatcher] C%d at Pack-off — processing %ss",
                cart.cart_id, PACKOFF_TIME,
            )

        elif job.job_type == JobType.MOVE_TO_BUFFER:
            cart.state = CartState.WAITING_FOR_STATION
            logger.info(
                "[Dispatcher] C%d buffered at %s — waiting for station",
                cart.cart_id, cart.pos,
            )

        elif job.job_type == JobType.RETURN_TO_BOX_DEPOT:
            cart.state = CartState.AT_BOX_DEPOT
            cart.process_timer = BOX_DEPOT_TIME
            cart.order = None
            self.completed_orders += 1
            start_t = self.cart_start_times.pop(cart.cart_id, None)
            if start_t is not None:
                cycle = self._sim_elapsed - start_t
                self.cycle_times.append(cycle)
                self.order_completion_times.append(self._sim_elapsed)
            logger.info(
                "[Dispatcher] C%d returned to Box Depot — completed orders: %d",
                cart.cart_id, self.completed_orders,
            )

        if agv:
            agv.current_job = None
        if job in self.active_jobs:
            self.active_jobs.remove(job)

    def _progress_jobs(
        self,
        agvs: list[AGV],
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        tiles: dict[tuple[int, int], Tile],
    ) -> None:
        """Monitor active jobs and advance them through phases."""
        for job in list(self.active_jobs):
            agv = job.assigned_agv
            if agv is None:
                continue

            if (
                agv.state == AGVState.IDLE
                and agv.carrying_cart is not None
                and agv.carrying_cart is job.cart
            ):
                self._set_transit_state(job)
                blocked = {a.pos for a in agvs if a is not agv}
                if agv.start_dropoff(job.target_pos, graph, tiles, blocked=blocked):
                    logger.info(
                        "[Dispatcher] AGV %d carrying C%d → %s (%d tiles)",
                        agv.agv_id, job.cart.cart_id,
                        job.target_pos, len(agv.path),
                    )
                else:
                    logger.info(
                        "[Dispatcher] AGV %d: no path to %s!",
                        agv.agv_id, job.target_pos,
                    )

            elif (
                agv.state == AGVState.IDLE
                and agv.carrying_cart is None
                and job.cart.carried_by is None
            ):
                self._complete_job(job)

    def _cancel_stuck_jobs(
        self,
        agvs: list[AGV],
        carts: list[Cart],
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        tiles: dict[tuple[int, int], Tile],
    ) -> None:
        """Cancel or retarget jobs for AGVs stuck too long."""
        for agv in agvs:
            if (
                not agv.is_blocked
                or agv.blocked_timer < JOB_CANCEL_TIMEOUT
                or agv.current_job is None
            ):
                continue

            job = agv.current_job

            # Case 1: stuck heading to pickup (not carrying yet) — cancel and re-queue
            if agv.carrying_cart is None and agv.state == AGVState.MOVING_TO_PICKUP:
                agv.current_job = None
                agv.state = AGVState.IDLE
                agv.path = []
                agv.path_index = 0
                agv.path_progress = 0.0
                agv.target = None
                agv.is_blocked = False
                agv.blocked_timer = 0.0
                if job in self.active_jobs:
                    self.active_jobs.remove(job)
                job.assigned_agv = None
                self.pending_jobs.append(job)
                logger.info(
                    "[Dispatcher] Cancelled stuck Job #%d (AGV %d) — re-queued",
                    job.job_id, agv.agv_id,
                )

            # Case 2: stuck while carrying a cart — retarget to nearest parking
            elif (
                agv.carrying_cart is not None
                and agv.state == AGVState.MOVING_TO_DROPOFF
            ):
                buffer = self._find_buffer_spot(agv.pos, carts, tiles)
                if buffer and agv.start_dropoff(buffer, graph, tiles):
                    job.target_pos = buffer
                    job.job_type = JobType.MOVE_TO_BUFFER
                    agv.blocked_timer = 0.0
                    agv.is_blocked = False
                    logger.info(
                        "[Dispatcher] Retargeted stuck AGV %d → buffer %s",
                        agv.agv_id, buffer,
                    )

    def _handle_blocked_agvs(
        self,
        agvs: list[AGV],
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        tiles: dict[tuple[int, int], Tile],
    ) -> None:
        """Re-route AGVs that have been blocked too long, nudge idle blockers."""
        for agv in agvs:
            if not agv.is_blocked or agv.blocked_timer < BLOCK_TIMEOUT:
                continue

            blocker = None
            if agv.path and agv.path_index < len(agv.path) - 1:
                next_tile = agv.path[agv.path_index + 1]
                for other in agvs:
                    if other is not agv and other.pos == next_tile:
                        blocker = other
                        break

            if (
                blocker
                and blocker.state == AGVState.IDLE
                and blocker.current_job is None
                and not blocker.carrying_cart
            ):
                agv_positions = {a.pos for a in agvs}
                best_tile = None
                best_dist = float("inf")
                for pos, tile in tiles.items():
                    if tile.tile_type in (TileType.PARKING, TileType.AGV_SPAWN):
                        if tile.station_id is not None:
                            continue  # skip station-associated parking
                        if pos not in agv_positions:
                            d = abs(pos[0] - blocker.pos[0]) + abs(pos[1] - blocker.pos[1])
                            if d < best_dist:
                                best_dist = d
                                best_tile = pos
                if best_tile and blocker.set_destination(best_tile, graph, tiles):
                    logger.info(
                        "[Collision] Nudged idle AGV %d from %s → %s",
                        blocker.agv_id, blocker.pos, best_tile,
                    )
                    agv.blocked_timer = 0.0
                continue

            # If blocker is actively moving (not itself stuck), wait briefly
            if (
                blocker
                and not blocker.is_blocked
                and blocker.state not in (AGVState.IDLE,)
                and agv.blocked_timer < BLOCK_TIMEOUT * 2
            ):
                continue

            if agv.blocked_timer - agv.last_reroute < REROUTE_COOLDOWN:
                continue
            if agv.reroute(graph, agvs, tiles):
                agv.last_reroute = agv.blocked_timer
                logger.info(
                    "[Collision] AGV %d re-routed (%d tiles)",
                    agv.agv_id, len(agv.path),
                )
            else:
                agv.last_reroute = agv.blocked_timer

    def _park_idle_agvs(
        self,
        agvs: list[AGV],
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        tiles: dict[tuple[int, int], Tile],
    ) -> None:
        """Send jobless idle AGVs off highway tiles to reduce corridor congestion."""
        agv_positions = {a.pos for a in agvs}
        for agv in agvs:
            if (
                agv.state != AGVState.IDLE
                or agv.current_job is not None
                or agv.carrying_cart is not None
            ):
                continue
            tile = tiles.get(agv.pos)
            if tile is None or tile.tile_type != TileType.HIGHWAY:
                continue
            # Find nearest parking/spawn tile not occupied by another AGV
            best: tuple[int, int] | None = None
            best_dist = float("inf")
            for pos, t in tiles.items():
                if t.tile_type not in (TileType.PARKING, TileType.AGV_SPAWN):
                    continue
                if t.station_id is not None:
                    continue  # skip station-associated parking
                if pos in agv_positions:
                    continue
                d = abs(pos[0] - agv.pos[0]) + abs(pos[1] - agv.pos[1])
                if d < best_dist:
                    best_dist = d
                    best = pos
            if best and agv.set_destination(best, graph, tiles):
                logger.info(
                    "[Dispatcher] Parking idle AGV %d off highway → %s",
                    agv.agv_id, best,
                )

    def get_station_tile_positions(
        self, station_id: str
    ) -> list[tuple[int, int]]:
        """Return list of PICK_STATION tile positions for a given station."""
        return self._station_tiles.get((station_id, TileType.PICK_STATION), [])

    def update(
        self,
        carts: list[Cart],
        agvs: list[AGV],
        graph: dict[tuple[int, int], set[tuple[int, int]]],
        tiles: dict[tuple[int, int], Tile],
        sim_elapsed: float = 0.0,
    ) -> None:
        """Main dispatcher tick — called each frame after AGV updates."""
        self._sim_elapsed = sim_elapsed
        self._station_fill_cache = self.get_station_fill(carts)
        self._cancel_stuck_jobs(agvs, carts, graph, tiles)
        self._create_jobs(carts, graph, tiles)
        self._assign_jobs(agvs, graph, tiles)
        self._progress_jobs(agvs, graph, tiles)
        self._handle_blocked_agvs(agvs, graph, tiles)
        self._park_idle_agvs(agvs, graph, tiles)

    def get_bottleneck_alerts(self, carts: list[Cart]) -> list[str]:
        """Return list of alert strings for current bottlenecks."""
        alerts: list[str] = []
        fill = self._station_fill_cache or self.get_station_fill(carts)

        po_cur, po_cap, po_rate = fill.get("Pack_off", (0, 4, 0.0))
        if po_cur >= po_cap:
            alerts.append("Pack-off FULL")
        elif len([
            j for j in self.pending_jobs + self.active_jobs
            if j.job_type == JobType.MOVE_TO_PACKOFF
        ]) > 3:
            alerts.append("Pack-off queue > 3")

        for i in range(1, 10):
            sid = f"S{i}"
            cur, cap, rate = fill.get(sid, (0, 0, 0.0))
            if cur >= cap and cap > 0:
                waiting = len([
                    j for j in self.pending_jobs + self.active_jobs
                    if j.station_id == sid
                ])
                if waiting > 0:
                    alerts.append(f"{sid} FULL ({waiting} waiting)")

        bd_cur, bd_cap, bd_rate = fill.get("Box_Depot", (0, 8, 0.0))
        spawned_count = sum(1 for c in carts if c.state == CartState.SPAWNED)
        if bd_cur >= bd_cap and spawned_count > 0:
            alerts.append(f"Box Depot FULL ({spawned_count} spawned)")

        return alerts

    def get_throughput_stats(self, sim_elapsed: float) -> dict[str, float]:
        """Return dict with completed, avg_cycle, per_hour."""
        completed = self.completed_orders
        avg_cycle = (
            sum(self.cycle_times) / len(self.cycle_times)
            if self.cycle_times
            else 0.0
        )
        per_hour = completed / (sim_elapsed / 3600.0) if sim_elapsed > 0 else 0.0
        return {
            "completed": completed,
            "avg_cycle": avg_cycle,
            "per_hour": per_hour,
        }
