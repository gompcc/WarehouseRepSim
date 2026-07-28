"""Zoning modes: nearest (default) vs balanced (equal same-side demand).

Balanced zoning is the structural fix for the flat-demand pathology where
the middle station of a big bank (S7: 447 of 2000 SKUs) became a
near-mandatory stop on ~99% of orders.
"""

import pytest

from agv_simulation.aisles import init_catalog
from agv_simulation.constants import NUM_SKUS
from agv_simulation.map_builder import build_map

SIDE_GROUPS = (("S1", "S3"), ("S2", "S4", "S6", "S8"), ("S5", "S7", "S9"))


def _counts(cat):
    return {s: len(v) for s, v in cat.station_skus.items()}


def test_nearest_is_default_and_hoards():
    cat = init_catalog(build_map())
    assert cat.zoning == "nearest"
    counts = _counts(cat)
    east = [counts[s] for s in ("S5", "S7", "S9")]
    assert max(east) - min(east) > 50  # S7 hoards the east bank


def test_balanced_equalizes_same_side_zones():
    cat = init_catalog(build_map(), zoning="balanced")
    counts = _counts(cat)
    assert sum(counts.values()) == NUM_SKUS
    for group in SIDE_GROUPS:
        vals = [counts[s] for s in group]
        assert max(vals) - min(vals) <= 1, (group, vals)


def test_balanced_keeps_side_constraint_and_walks():
    cat = init_catalog(build_map(), zoning="balanced")
    for sku, slot in cat.slots.items():
        # ownership never crosses the highway
        assert cat.station_side[slot.station] == slot.bank
        assert cat.walk_distance(slot.station, sku) > 0
    # zone borders still computable for the map overlay
    assert cat.zone_border_segments()


def test_balanced_is_deterministic():
    a = _counts(init_catalog(build_map(), zoning="balanced"))
    b = _counts(init_catalog(build_map(), zoning="balanced"))
    assert a == b


def test_unknown_zoning_rejected():
    with pytest.raises(ValueError):
        init_catalog(build_map(), zoning="bogus")
