"""Toggleable dispatch strategy modules.

Each module isolates one structural improvement to the baseline dispatcher
and can be switched on/off independently (GUI switches or headless config)
to measure its throughput impact under a seeded, controlled environment.
"""

from .config import StrategyConfig, StrategyInfo, STRATEGY_INFO
from .distances import DistanceMap
from .eta_reservations import ETAReservations
from .global_assignment import GlobalAssignment

__all__ = [
    "StrategyConfig",
    "StrategyInfo",
    "STRATEGY_INFO",
    "DistanceMap",
    "ETAReservations",
    "GlobalAssignment",
]
