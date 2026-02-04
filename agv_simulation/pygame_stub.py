"""Stub out pygame for headless/test usage."""

from __future__ import annotations

import sys
import types


def install() -> None:
    """Install a minimal pygame stub into ``sys.modules``."""
    _pg = types.ModuleType("pygame")
    _pg.init = lambda: None  # type: ignore[attr-defined]
    _pg.quit = lambda: None  # type: ignore[attr-defined]
    _pg.display = types.ModuleType("pygame.display")
    _pg.display.set_mode = lambda *a, **k: None  # type: ignore[attr-defined]
    _pg.display.set_caption = lambda *a, **k: None  # type: ignore[attr-defined]
    _pg.font = types.ModuleType("pygame.font")
    _pg.font.SysFont = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["pygame"] = _pg
    sys.modules["pygame.display"] = _pg.display
    sys.modules["pygame.font"] = _pg.font
