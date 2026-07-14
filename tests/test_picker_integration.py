"""Picker release-rule integration (PRD §14.6): SKU orders gate cart release."""

from agv_simulation.enums import CartState, JobType, TileType
from agv_simulation.map_builder import build_map, build_graph
from agv_simulation.aisles import init_catalog, get_catalog
from agv_simulation.models import Cart, Job, Order, set_order_seed
from agv_simulation.picker import PickerManager
from agv_simulation.dispatcher import Dispatcher


def _world():
    tiles = build_map()
    init_catalog(tiles)
    return tiles, build_graph(tiles)


def _station_tile(tiles, sid):
    return next(
        pos for pos, t in tiles.items()
        if t.tile_type == TileType.PICK_STATION and t.station_id == sid
    )


def _order_with_station(sid_num):
    """Create seeded orders until one visits the wanted station."""
    set_order_seed(7)
    try:
        for _ in range(200):
            order = Order()
            if sid_num in order.stations_to_visit:
                return order
        raise AssertionError(f"no seeded order visits S{sid_num}")
    finally:
        set_order_seed(None)


def test_orders_are_sku_based_and_zone_consistent():
    _world()
    cat = get_catalog()
    set_order_seed(11)
    try:
        orders = [Order() for _ in range(200)]
    finally:
        set_order_seed(None)
    for order in orders:
        assert 1 <= len(order.stations_to_visit) <= 9
        for num, skus in order.skus_by_station.items():
            assert len(skus) >= 1
            for sku in skus:
                # Every SKU must genuinely belong to that station's zone
                assert cat.slots[sku].station == f"S{num}"
    totals = [len(o.lines) for o in orders]
    mean = sum(totals) / len(totals)
    assert 18.0 < mean < 22.0, mean  # target μ20 σ9, min 1
    var = sum((t - mean) ** 2 for t in totals) / len(totals)
    assert 7.0 < var ** 0.5 < 11.0, var ** 0.5  # sd ≈ 9
    for o in orders:
        assert len(set(o.lines)) == len(o.lines)  # distinct SKU lines


def test_release_rule_holds_cart_until_picked():
    tiles, graph = _world()
    manager = PickerManager(tiles)
    dispatcher = Dispatcher(tiles, pickers=manager)
    assert manager.gating

    pos = _station_tile(tiles, "S1")
    cart = Cart(pos)
    cart.order = _order_with_station(1)
    job = Job(JobType.MOVE_TO_PICK, cart, pos, station_id="S1")
    dispatcher._complete_job(job)

    assert cart.state == CartState.PICKING
    assert cart.process_timer == 0.0
    # Station must NOT be pre-completed (legacy behavior completed on arrival)
    assert 1 not in cart.order.completed_stations

    # While the picker works, the dispatcher must not create onward jobs
    lines = cart.order.lines_at_station(1)
    manager.update(0.1, [cart])  # queue + assign
    dispatcher._create_jobs([cart], [], graph, tiles)
    assert dispatcher.pending_jobs == []
    assert not dispatcher._picking_done(cart)

    # Run until the picker finishes every line (worst case ~10 x 65s)
    for _ in range(20000):
        manager.update(0.1, [cart])
        if dispatcher._picking_done(cart):
            break
    assert dispatcher._picking_done(cart)
    assert cart.order.lines_remaining_at(1) == []
    assert 1 in cart.order.completed_stations
    assert manager.picks_done == lines


def test_buffered_cart_resumes_remaining_lines():
    tiles, _ = _world()
    manager = PickerManager(tiles)
    Dispatcher(tiles, pickers=manager)  # sets gating

    pos = _station_tile(tiles, "S1")
    cart = Cart(pos)
    cart.order = _order_with_station(1)
    # Ensure multi-line so we can interrupt mid-list
    cart.order.skus_by_station[1] = cart.order.skus_by_station[1][:1] + \
        get_catalog().station_skus["S1"][:3]
    cart.state = CartState.PICKING

    # Serve until exactly one line is picked, then buffer the cart away
    while manager.picks_done < 1:
        manager.update(0.1, [cart])
    picked_before = set(cart.order.picked_skus)
    assert len(picked_before) == 1
    cart.state = CartState.WAITING_FOR_STATION
    for _ in range(600):
        manager.update(0.1, [cart])
    assert manager.carts_left_early == 1
    assert 1 not in cart.order.completed_stations  # incomplete: must resume

    # Cart returns — picker must do ONLY the remaining lines, no re-picks
    remaining_before = set(cart.order.lines_remaining_at(1))
    cart.state = CartState.PICKING
    for _ in range(20000):
        manager.update(0.1, [cart])
        if not cart.order.lines_remaining_at(1):
            break
    assert cart.order.lines_remaining_at(1) == []
    assert 1 in cart.order.completed_stations
    assert manager.picks_done == 1 + len(remaining_before)
    assert picked_before <= cart.order.picked_skus


def test_bare_dispatcher_is_still_picker_gated():
    """No flat-timer mode exists: even a Dispatcher built without an explicit
    PickerManager creates one and gates carts on it."""
    tiles, _ = _world()
    dispatcher = Dispatcher(tiles)
    assert dispatcher.pickers is not None and dispatcher.pickers.gating
    pos = _station_tile(tiles, "S1")
    cart = Cart(pos)
    cart.order = _order_with_station(1)
    job = Job(JobType.MOVE_TO_PICK, cart, pos, station_id="S1")
    dispatcher._complete_job(job)
    assert cart.process_timer == 0.0
    assert 1 not in cart.order.completed_stations
    assert not dispatcher._picking_done(cart)  # lines remain unpicked


def test_served_cart_lingering_in_picking_stays_released():
    """Regression: a served cart stuck in PICKING (next station full) must
    NOT be re-queued with an empty pick list — that re-tracks it and makes
    cart_done() False forever (observed as a full-warehouse deadlock)."""
    tiles, _ = _world()
    manager = PickerManager(tiles)
    Dispatcher(tiles, pickers=manager)

    pos = _station_tile(tiles, "S1")
    cart = Cart(pos)
    cart.order = _order_with_station(1)
    cart.state = CartState.PICKING
    for _ in range(20000):
        manager.update(0.1, [cart])
        if not cart.order.lines_remaining_at(1):
            break
    assert manager.cart_done(cart)

    # Cart lingers in PICKING at the same tile (no onward capacity)
    for _ in range(500):
        manager.update(0.1, [cart])
    assert manager.cart_done(cart)          # must stay released
    assert manager.carts_served == 1        # never re-served
    assert cart.cart_id not in manager._tracked


def test_picking_cart_not_flagged_stuck_while_queued():
    """A cart waiting on a busy picker is workload, not a stuck event."""
    from agv_simulation.environment import Environment

    env = Environment(stuck_threshold=5.0)
    pos = _station_tile(env.tiles, "S1")
    c1, c2 = Cart(pos), Cart(_station_tile(env.tiles, "S1"))
    # Two carts, one picker: the second queues behind the first
    s1_tiles = [
        p for p, t in env.tiles.items()
        if t.tile_type == TileType.PICK_STATION and t.station_id == "S1"
    ]
    c1.pos, c2.pos = s1_tiles[0], s1_tiles[1]
    c1.order, c2.order = _order_with_station(1), _order_with_station(1)
    c1.state = c2.state = CartState.PICKING
    env.carts.extend([c1, c2])

    for _ in range(300):  # 30 sim-seconds >> 5s stuck threshold
        env.step(0.1)
        env.audit(0.1)
    assert env.events.counters.get("stuck", 0) == 0
