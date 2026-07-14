"""Travel-aware order sequencing.

The baseline scorer compares *Manhattan* distances, which underprice
cross-bank trips ~2x (the left S1–S4 and right S5–S9 banks only connect via
the top/bottom highways), so a cart bounces between banks whenever a
far-side station looks marginally emptier.

This module restricts the candidate set for the next visit to a window of
the ``WINDOW`` remaining stations nearest by *true directed distance* —
keeping carts working through the near bank before crossing. The active
scorer — baseline greedy or ETA reservations — then chooses within that
window, composing cleanly with the other toggles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .distances import DistanceMap

if TYPE_CHECKING:
    from ..models import Cart

# How many nearest-by-travel stations the scorer may choose between.
# 1 = strict nearest-first; larger windows allow skipping a crowded station
# without permitting expensive cross-bank detours.
WINDOW = 3


class OrderSequencing:
    """Travel-ordered station sequencer (toggle: ``order_sequencing``)."""

    def __init__(self, dist_map: DistanceMap) -> None:
        self.dist_map = dist_map

    def order_candidates(self, cart: Cart, remaining: list[int]) -> list[int]:
        """Remaining stations sorted by true directed distance, windowed."""
        ordered = sorted(
            remaining,
            key=lambda s: self.dist_map.hops_to_station(cart.pos, f"S{s}"),
        )
        return ordered[:WINDOW]
