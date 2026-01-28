#!/usr/bin/env python3
"""Test runner that stubs pygame and loads phase5 as agv_simulation."""
import sys
import types
import importlib.util

_pg = types.ModuleType("pygame")
_pg.init = lambda: None
_pg.quit = lambda: None
_pg.display = types.ModuleType("pygame.display")
_pg.display.set_mode = lambda *a, **k: None
_pg.display.set_caption = lambda *a, **k: None
_pg.font = types.ModuleType("pygame.font")
_pg.font.SysFont = lambda *a, **k: None
sys.modules["pygame"] = _pg
sys.modules["pygame.display"] = _pg.display
sys.modules["pygame.font"] = _pg.font

spec = importlib.util.spec_from_file_location(
    "agv_simulation", "phases/phase5_multiple_agvs.py"
)
mod = importlib.util.module_from_spec(spec)
sys.modules["agv_simulation"] = mod
spec.loader.exec_module(mod)

import pytest
sys.exit(pytest.main(["-v", "test_collision_avoidance.py"]))
