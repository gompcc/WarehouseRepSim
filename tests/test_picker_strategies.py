"""Picker strategies: static (station-bound) vs dynamic (roam within side).

Dynamic pickers may relocate to the worst backlog on their OWN side of the
highway — never across it — and the inter-station walk costs real time.
"""

from agv_simulation.enums import CartState, TileType
from agv_simulation.map_builder import build_map
from agv_simulation.aisles import get_catalog, init_catalog
from agv_simulation.models import Cart
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


def _run(manager, carts, max_ticks=40000):
    """Advance until every cart is served (or the tick budget runs out)."""
    for _ in range(max_ticks):
        manager.update(0.1, carts)
        if manager.carts_served >= len(carts):
            return
    raise AssertionError(
        f"only {manager.carts_served}/{len(carts)} carts served in budget"
    )


def test_static_never_relocates():
    tiles = _world()
    manager = PickerManager(tiles)  # default strategy
    assert manager.strategy == "static"
    carts = [_picking_cart(tiles, "S3", 0), _picking_cart(tiles, "S3", 1)]
    _run(manager, carts)
    assert manager.relocations == 0
    for crew_sid, crew in manager.pickers.items():
        for picker in crew:
            assert picker.station_id == crew_sid  # nobody moved


def test_dynamic_relocates_to_backlog_on_own_side():
    tiles = _world()
    manager = PickerManager(tiles, strategy="dynamic")
    # Two carts at S3 (west side): S3's own picker takes the first, and the
    # only other west picker (S1's) must walk over for the second
    carts = [_picking_cart(tiles, "S3", 0), _picking_cart(tiles, "S3", 1)]
    _run(manager, carts)
    assert manager.relocations >= 1
    assert manager.relocation_seconds > 0.0
    s1_picker = manager.pickers["S1"][0]
    assert s1_picker.station_id == "S3"  # relocated and stayed
    # Both carts fully served, none left early
    assert manager.carts_served == 2
    assert manager.carts_left_early == 0


def test_dynamic_never_crosses_the_highway():
    tiles = _world()
    manager = PickerManager(tiles, strategy="dynamic")
    side = get_catalog().station_side
    # Three carts at S5 (east side, capacity 3): S5's picker plus exactly
    # the east-side helpers (S7/S9) may serve them — never west/central
    carts = [_picking_cart(tiles, "S5", i) for i in range(3)]
    _run(manager, carts)
    for crew_sid, crew in manager.pickers.items():
        for picker in crew:
            assert side[picker.station_id] == side[crew_sid], (
                f"picker from {crew_sid} crossed to {picker.station_id}"
            )
    # West and central pickers specifically must not have moved at all
    for sid in ("S1", "S2", "S3", "S4", "S6", "S8"):
        for picker in manager.pickers[sid]:
            assert picker.station_id == sid


def test_added_picker_serves_in_parallel():
    """GUI station click hires an extra picker; both work the same queue."""
    tiles = _world()
    manager = PickerManager(tiles)
    manager.add_picker("S3")
    assert len(manager.pickers["S3"]) == 2
    carts = [_picking_cart(tiles, "S3", 0), _picking_cart(tiles, "S3", 1)]
    for _ in range(5):
        manager.update(0.1, carts)
    busy = [p for p in manager.pickers["S3"] if p.cart is not None]
    assert len(busy) == 2          # served simultaneously, no relocation
    assert manager.relocations == 0
    _run(manager, carts)
    assert manager.carts_served == 2


def test_added_picker_roams_when_dynamic():
    """A hired picker participates in dynamic roaming on its side."""
    tiles = _world()
    manager = PickerManager(tiles, strategy="dynamic")
    manager.add_picker("S9")  # east side
    # Three carts at S5: S5's picker + two east helpers can cover them
    carts = [_picking_cart(tiles, "S5", i) for i in range(3)]
    _run(manager, carts)
    assert manager.carts_served == 3
    # The hired picker (2nd in S9's crew) must have relocated within east
    hired = manager.pickers["S9"][1]
    assert hired.station_id in ("S5", "S7", "S9")


def test_dynamic_relocation_takes_real_time():
    tiles = _world()
    manager = PickerManager(tiles, strategy="dynamic")
    carts = [_picking_cart(tiles, "S3", 0), _picking_cart(tiles, "S3", 1)]
    # Let assignment happen (a few ticks), then find the relocating picker
    for _ in range(5):
        manager.update(0.1, carts)
    s1_picker = manager.pickers["S1"][0]
    assert s1_picker.state == Picker.MOVE_STATION
    assert s1_picker.leg_time > 0.0
    # While walking between stations the picker counts as busy
    busy_before = manager.busy_seconds
    manager.update(0.1, carts)
    assert manager.busy_seconds > busy_before
