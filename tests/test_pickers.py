"""Shadow-mode picker tests (PRD §14.9): calibration, service cycle, abort."""

from agv_simulation.enums import CartState, TileType
from agv_simulation.map_builder import build_map
from agv_simulation.aisles import init_catalog, walk_time_seconds
from agv_simulation.models import Cart
from agv_simulation.picker import Picker, PickerManager


def _setup():
    tiles = build_map()
    init_catalog(tiles)
    return tiles


def _s1_tile(tiles):
    return next(
        pos for pos, t in tiles.items()
        if t.tile_type == TileType.PICK_STATION and t.station_id == "S1"
    )


def test_walk_time_calibration_targets():
    """User spec: mean 30 s, sd 10 s round trip; near ~20 s, far ~40 s."""
    tiles = _setup()
    from agv_simulation.aisles import get_catalog
    calib = get_catalog().calibration_stats()
    assert abs(calib["mean_s"] - 30.0) < 0.5, calib
    assert abs(calib["sd_s"] - 10.0) < 1.0, calib
    assert 17.0 <= calib["near_p16_s"] <= 23.0, calib
    assert 37.0 <= calib["far_p84_s"] <= 45.0, calib


def test_picker_serves_cart_and_records_stats():
    tiles = _setup()
    manager = PickerManager(tiles)
    cart = Cart(_s1_tile(tiles))
    cart.state = CartState.PICKING
    cart.carried_by = None

    # Long enough for any sampled pick list: worst case ~7 picks x ~65 s
    for _ in range(9000):
        manager.update(0.1, [cart])
        if manager.carts_served:
            break

    stats = manager.stats()
    assert stats["carts_served"] == 1
    assert stats["picks_done"] >= 1
    assert stats["carts_left_early"] == 0
    # Shadow mode must not touch the cart
    assert cart.state == CartState.PICKING
    # Walk times must be in the calibrated envelope
    assert 5.0 < stats["walk_mean_s"] < 60.0
    assert manager.cart_done(cart)


def test_cart_leaving_early_aborts_picker():
    tiles = _setup()
    manager = PickerManager(tiles)
    cart = Cart(_s1_tile(tiles))
    cart.state = CartState.PICKING
    cart.carried_by = None

    # Let the picker start walking
    for _ in range(30):
        manager.update(0.1, [cart])
    crew = manager.pickers["S1"]
    assert any(p.state != Picker.IDLE for p in crew)

    # Cart departs mid-service
    cart.state = CartState.IN_TRANSIT_TO_PACKOFF
    for _ in range(1200):
        manager.update(0.1, [cart])

    assert manager.carts_left_early == 1
    assert manager.carts_served == 0
    assert all(p.state == Picker.IDLE for p in crew)
    assert manager.cart_done(cart)


def test_pick_counts_track_target_distribution():
    """Sampled picks per visit should average ~4 (sd 2, min 1)."""
    tiles = _setup()
    manager = PickerManager(tiles)
    counts = [len(manager._sample_picks("S5")) for _ in range(500)]
    mean = sum(counts) / len(counts)
    assert 3.4 < mean < 4.6, mean
    assert min(counts) >= 1


def test_walk_time_monotone_in_distance():
    assert walk_time_seconds(5.0) < walk_time_seconds(15.0) < walk_time_seconds(30.0)
