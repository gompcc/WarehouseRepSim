"""Picker strategies: static (station-bound) vs dynamic (two labour pools).

Dynamic pickers share labour in two pools that never mix: the OUTER pool
(west S1/S3 + east S5/S7/S9) reaches across the warehouse by walking around
the OUTSIDE of the AGV track (over the top above the Box Depot, or under the
East Highway — the shorter detour), and the CENTRAL pool (S2/S4/S6/S8)
shares within the island between the pillars. Relocation costs real time.
"""

from agv_simulation.constants import METERS_PER_TILE
from agv_simulation.enums import CartState, TileType
from agv_simulation.map_builder import build_map
from agv_simulation.aisles import init_catalog
from agv_simulation.models import Cart
from agv_simulation.picker import (
    _SOUTH_DETOUR_ROW, Picker, PickerManager,
)

OUTER = {"S1", "S3", "S5", "S7", "S9"}
CENTRAL = {"S2", "S4", "S6", "S8"}


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
    # Helpers relocated, stayed, and were RE-HOMED into S3's live crew
    # (the whole idle outer pool may converge on the backlog)
    assert len(manager.pickers["S3"]) >= 2
    assert len(manager.pickers["S1"]) == 0
    assert len(manager.all_pickers()) == 9  # nobody lost in re-homing
    # Crew lists always match live station_id (management/stats depend on it)
    for sid, crew in manager.pickers.items():
        assert all(p.station_id == sid for p in crew)
    # Both carts fully served, none left early
    assert manager.carts_served == 2
    assert manager.carts_left_early == 0


def test_dynamic_pools_never_mix():
    tiles = _world()
    manager = PickerManager(tiles, strategy="dynamic")
    # Three carts at S5 (outer pool): only outer-pool pickers (S1/S3/S7/S9
    # helpers) may serve them — central pickers must not move
    carts = [_picking_cart(tiles, "S5", i) for i in range(3)]
    _run(manager, carts)
    for crew_sid, crew in manager.pickers.items():
        for picker in crew:
            same_pool = (
                (crew_sid in OUTER) == (picker.station_id in OUTER)
            )
            assert same_pool, (
                f"picker from {crew_sid} left its pool to {picker.station_id}"
            )
    for sid in CENTRAL:
        for picker in manager.pickers[sid]:
            assert picker.station_id == sid


def test_outer_pool_shares_across_the_track():
    """S1/S3 (west) may help S5/S7/S9 (east) by walking around the outside
    of the track — the detour time is charged, not straight-line time."""
    tiles = _world()
    manager = PickerManager(tiles, strategy="dynamic")
    # Enough carts at S9 to exhaust the east helpers and pull in west crew:
    # S9 has 4 pick slots; S5/S7/S9 supply 3 outer-east pickers, so a 4th
    # concurrent cart needs a west picker to cross
    carts = [_picking_cart(tiles, "S9", i) for i in range(4)]
    _run(manager, carts)
    # Crossed helpers re-home into east crews: live east headcount grew
    # beyond the three east-hired pickers
    east_live = [
        p for p in manager.all_pickers()
        if p.station_id in ("S5", "S7", "S9")
    ]
    assert len(east_live) > 3, "no west picker crossed to help the east backlog"
    assert manager.relocation_seconds > 0.0


def test_cross_track_distance_is_the_south_detour():
    """West↔east moves ALWAYS go around the south side (user decision
    2026-07-15) — never straight across, never over the top."""
    tiles = _world()
    manager = PickerManager(tiles, strategy="dynamic")
    (ax, ay) = manager.station_positions["S1"]
    (bx, by) = manager.station_positions["S9"]
    south = (_SOUTH_DETOUR_ROW - ay) + abs(ax - bx) + (_SOUTH_DETOUR_ROW - by)
    got = manager._station_dist_m("S1", "S9")
    assert got == south * METERS_PER_TILE
    # and it must exceed the (illegal) straight Manhattan line
    manhattan = (abs(ax - bx) + abs(ay - by)) * METERS_PER_TILE
    assert got > manhattan
    # same-side stays Manhattan
    (cx, cy) = manager.station_positions["S3"]
    assert manager._station_dist_m("S1", "S3") == (
        (abs(ax - cx) + abs(ay - cy)) * METERS_PER_TILE
    )
    # the animation path for a cross move hugs the south detour row
    path = manager._relocate_path("S1", "S9")
    assert path is not None
    assert {p[1] for p in path[1:3]} == {_SOUTH_DETOUR_ROW}
    assert manager._relocate_path("S1", "S3") is None


def test_management_hires_most_overloaded_station_first():
    """The headcount budget goes to the worst queue, not to whichever
    station sorts first alphabetically."""
    tiles = _world()
    manager = PickerManager(tiles, management=True)
    # S8 drowning (4 carts), S1 mildly busy (1 cart): first review's first
    # hire must land on S8 even though S1 sorts earlier
    carts = [_picking_cart(tiles, "S8", i) for i in range(4)]
    carts.append(_picking_cart(tiles, "S1", 0))
    for _ in range(3010):
        manager.update(0.1, carts)
    assert manager.managed_hires >= 1
    assert len(manager.pickers["S8"]) > 1, (
        "most overloaded station was not staffed first"
    )


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
    assert len(manager.all_pickers()) == 10  # nobody lost in re-homing
    # Everyone stays in the outer/central pool they belong to, and crew
    # lists track live station_id
    for sid, crew in manager.pickers.items():
        for p in crew:
            assert p.station_id == sid
            assert (sid in OUTER) == (p.station_id in OUTER)


def test_one_order_shared_by_many_pickers():
    """User spec: when a cart arrives, its order can be picked by MANY
    pickers concurrently — hiring must speed up a single cart, not just
    parallel carts."""
    tiles = _world()
    manager = PickerManager(tiles)
    manager.add_picker("S3")
    manager.add_picker("S3")  # crew of 3
    cart = _picking_cart(tiles, "S3")
    for _ in range(5):
        manager.update(0.1, [cart])
    on_cart = [
        p for p in manager.pickers["S3"]
        if p.cart is not None and p.cart.cart_id == cart.cart_id
    ]
    assert len(on_cart) >= 2, "order not shared across pickers"
    _run(manager, [cart])
    assert manager.carts_served == 1          # closed out exactly once
    assert manager.carts_left_early == 0


def test_shared_order_completes_faster_with_more_pickers():
    """Crew size must cut a single cart's dwell (diminishing-returns fix)."""
    def dwell_ticks(extra_pickers):
        tiles = _world()
        manager = PickerManager(tiles)
        for _ in range(extra_pickers):
            manager.add_picker("S3")
        cart = _picking_cart(tiles, "S3")
        for tick in range(40000):
            manager.update(0.1, [cart])
            if manager.carts_served == 1:
                return tick
        raise AssertionError("cart never served")

    solo = dwell_ticks(0)
    crew = dwell_ticks(2)
    assert crew < solo * 0.6, (solo, crew)  # 3 pickers ≥ ~1.7x faster


def test_picker_management_scales_crew_up_and_down():
    """Auto-staffing (queueing control): a flooded station gains pickers at
    the next review; an idle one releases them back down to 1."""
    tiles = _world()
    manager = PickerManager(tiles, management=True)
    carts = [_picking_cart(tiles, "S3", i) for i in range(4)]
    for _ in range(3100):   # past one MANAGE_INTERVAL (300 sim-s)
        manager.update(0.1, carts)
    assert manager.managed_hires >= 1
    assert len(manager.pickers["S3"]) > 1
    # Demand gone: reviews release the extra crew (never below 1)
    for _ in range(70000):
        manager.update(0.1, [])
        if len(manager.pickers["S3"]) == 1:
            break
    assert len(manager.pickers["S3"]) == 1
    assert manager.managed_releases >= 1


def test_management_toggle_mid_run_does_not_spur_hire():
    """Regression: flipping management ON mid-session must seed the review
    baseline — otherwise the first review reads every pick since world
    start as one window's demand and hires everywhere."""
    tiles = _world()
    manager = PickerManager(tiles)  # management off
    carts = [_picking_cart(tiles, "S3", 0), _picking_cart(tiles, "S3", 1)]
    _run(manager, carts)            # accumulate real picks first
    manager.set_management(True)
    for _ in range(3100):           # one full review interval, zero demand
        manager.update(0.1, [])
    assert manager.managed_hires == 0, "spur-hire on stale pick counters"


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
