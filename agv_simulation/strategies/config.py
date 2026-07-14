"""Strategy toggle configuration.

Each strategy is an isolated module that can be switched on/off at runtime
(GUI toggle switches or headless ``strategies=`` config) without touching
baseline dispatcher behavior: with every toggle off, the dispatcher runs
byte-identical baseline logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StrategyConfig:
    """On/off switches for the dispatch strategy modules.

    (Travel-window sequencing over true directed distances started as a
    third toggle; it proved a consistent win and is now baked into the
    baseline dispatcher — see ``Dispatcher._travel_window``.)
    """

    eta_reservations: bool = False
    global_assignment: bool = False

    def active_names(self) -> list[str]:
        """Short names of enabled strategies (for logs/exports)."""
        return [info.key for info in STRATEGY_INFO if getattr(self, info.attr)]

    def any_active(self) -> bool:
        return any(getattr(self, info.attr) for info in STRATEGY_INFO)


@dataclass(frozen=True)
class StrategyInfo:
    """Display metadata for one strategy (GUI toggles, exports)."""

    attr: str    # StrategyConfig attribute name
    key: str     # short name for logs/exports
    label: str   # GUI toggle label


STRATEGY_INFO: list[StrategyInfo] = [
    StrategyInfo("eta_reservations", "eta", "ETA reservations"),
    StrategyInfo("global_assignment", "hungarian", "Global assignment"),
]
