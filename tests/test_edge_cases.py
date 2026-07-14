"""Edge cases flagged by the 2026-07-14 test-gap review: fleet resizing,
dynamic-picker aborts mid-relocation, shared-order departures, and order-book
boundary behavior. These are the failure modes that would silently corrupt
experiment results if regressed.
"""

from agv_simulation.enums import AGVState, CartState, TileType
from agv_simulation.environment import Environment
from agv_simulation.map_builder import build_map
from agv_simulation.aisles import init_catalog
from agv_simulation.models import Cart, Order, set_order_book, set_order_seed
from agv_simulation.picker import Picker, PickerManager


def _world():
    tiles = build_map()
    init_catalog(tiles)
    return tiles


def _station_tiles(tiles, sid):
    return [
        pos for pos, t in tiles.items()
        if t.tile_type == TileType.PICK_STATION and t.station_id == sid
    ]


def _picking_cart(tiles, sid, idx=0):
    cart = Cart(_station_tiles(tiles, sid)[idx])
    cart.state = CartState.PICKING
    return cart


# ---------------------------------------------------------------- fleet


def test_retarget_fleet_arithmetic_grow_shrink_regrow():
    env = Environment()
    env.retarget_fleet(5, 10)
    assert (env.agv_preload_remaining, env.preload_remaining) == (5, 10)
    assert env.agv_retire_pending == env.cart_retire_pending == 0

    env.retarget_fleet(2, 4)  # shrink cancels queued spawns first
    assert (env.agv_preload_remaining, env.preload_remaining) == (2, 4)
    assert env.agv_retire_pending == env.cart_retire_pending == 0

    env.retarget_fleet(6, 8)  # regrow — never negative, no double count
    assert (env.agv_preload_remaining, env.preload_remaining) == (6, 8)


def test_retire_tick_never_removes_busy_units():
    env = Environment()
    agv = env.spawn_agv()
    agv.state = AGVState.MOVING_TO_DROPOFF
    agv.current_job = object()
    env.agv_retire_pending = 1
    env._retire_tick()
    assert agv in env.agvs  # mid-job: must NOT retire

    agv.state = AGVState.IDLE
    agv.current_job = None
    env._retire_tick()
    assert agv not in env.agvs  # retires once safe
    assert env.agv_retire_pending == 0


def test_retire_tick_only_takes_orderless_depot_carts():
    env = Environment()
    for _ in range(3):
        env.spawn_cart()
    env.carts[0].order = Order.__new__(Order)  # any order object => busy
    env.cart_retire_pending = 3
    env._retire_tick()
    assert len(env.carts) == 1          # two order-less carts retired
    assert env.carts[0].order is not None
    assert env.cart_retire_pending == 1  # remaining retirement stays pending


# ---------------------------------------------------------- picker aborts


def test_dynamic_abort_mid_relocation_recovers():
    tiles = _world()
    manager = PickerManager(tiles, strategy="dynamic")
    carts = [_picking_cart(tiles, "S3", 0), _picking_cart(tiles, "S3", 1)]
    for _ in range(5):
        manager.update(0.1, carts)
    s1 = manager.pickers["S1"][0]
    assert s1.state == Picker.MOVE_STATION  # walking S1 -> S3

    carts[1].state = CartState.IN_TRANSIT_TO_PACKOFF  # target leaves mid-walk
    for _ in range(3000):
        manager.update(0.1, carts)
        if s1.state == Picker.IDLE and manager.carts_served >= 1:
            break
    assert s1.state == Picker.IDLE           # recovers, no phantom pick
    assert s1.cart is None
    assert manager.carts_left_early == 1     # counted exactly once
    assert carts[1].cart_id not in manager._tracked


def test_shared_cart_departure_counted_once():
    tiles = _world()
    manager = PickerManager(tiles)
    manager.add_picker("S3")
    manager.add_picker("S3")
    cart = _picking_cart(tiles, "S3")
    for _ in range(5):
        manager.update(0.1, [cart])
    assert sum(
        1 for p in manager.pickers["S3"]
        if p.cart is not None and p.cart.cart_id == cart.cart_id
    ) >= 2

    cart.state = CartState.IN_TRANSIT_TO_PACKOFF
    for _ in range(2000):
        manager.update(0.1, [cart])
    assert manager.carts_left_early == 1     # once, not per picker/line
    assert cart.cart_id not in manager._tracked
    assert all(p.state == Picker.IDLE for p in manager.pickers["S3"])


# ------------------------------------------------------------ order book


def test_order_book_wraps_past_the_end():
    _world()
    set_order_book([[1], [2], [3]])
    set_order_seed(None)  # offset 0
    try:
        Order._next_id = 4
        assert Order().lines == [1]  # wrapped to the start
        assert Order().lines == [2]
    finally:
        set_order_book(None)
        Order._next_id = 1


def test_empty_book_falls_back_to_sampling():
    """Pins current behavior: an empty book is falsy, so Order() silently
    samples randomly. If this becomes an error instead, update this test —
    that would be a conscious improvement, not a regression."""
    _world()
    set_order_book([])
    set_order_seed(7)
    try:
        Order._next_id = 1
        order = Order()
        assert len(order.lines) >= 1  # sampled, not crashed
    finally:
        set_order_book(None)
        set_order_seed(None)
        Order._next_id = 1
