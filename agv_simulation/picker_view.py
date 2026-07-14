"""GUI layer for the shadow-mode pickers: walking dots + assumptions box.

Kept in its own module so the hookup into the shared ``renderer.render()``
is two lines — the picker subsystem stays independent (PRD §14.9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from .constants import (
    TILE_SIZE, PICKER_WALK_SPEED, PICK_GRAB_TIME, PICKERS_PER_STATION,
    LABEL_BG, OUTLINE_COLOR,
)
from .aisles import get_catalog
from .picker import Picker
from .constants import ORDER_LINES_MEAN, ORDER_LINES_SD

if TYPE_CHECKING:
    from .picker import PickerManager

_COLOR_WALK = (20, 150, 60)
_COLOR_GRAB = (235, 140, 0)
_COLOR_IDLE = (120, 120, 130)
_TEXT = (35, 35, 35)


def draw_pickers(surface: pygame.Surface, manager: PickerManager) -> None:
    """Draw every picker as a dot at its interpolated aisle position."""
    for picker in manager.all_pickers():
        px = int(picker.pos[0] * TILE_SIZE + TILE_SIZE // 2)
        py = int(picker.pos[1] * TILE_SIZE + TILE_SIZE // 2)
        if picker.state == Picker.IDLE:
            color = _COLOR_IDLE
        elif picker.state == Picker.GRAB:
            color = _COLOR_GRAB
        else:
            color = _COLOR_WALK
        pygame.draw.circle(surface, color, (px, py), 4)
        pygame.draw.circle(surface, (0, 0, 0), (px, py), 4, 1)


def draw_picker_info(
    surface: pygame.Surface,
    manager: PickerManager,
    font: pygame.font.Font,
    x: int = 6,
    y: int = 6,
) -> None:
    """Assumptions + live shadow stats, in the empty corner above the west bank."""
    calib = get_catalog().calibration_stats()
    live = manager.stats()
    lines = [
        "PICKERS (gating carts)" if manager.gating else "PICKERS (shadow mode)",
        f"{PICKERS_PER_STATION}/station · {PICKER_WALK_SPEED} m/s · grab {PICK_GRAB_TIME:.0f}s",
        f"lines/order: μ{ORDER_LINES_MEAN:.0f} σ{ORDER_LINES_SD:.0f}",
        f"walk/pick: μ{calib['mean_s']:.0f}s σ{calib['sd_s']:.0f}"
        f" (near {calib['near_p16_s']:.0f} / far {calib['far_p84_s']:.0f})",
        f"live: {live['picks_done']} picks"
        f" · μ{live['walk_mean_s']:.0f}s · busy {live['busy_fraction']:.0%}",
        f"carts: {live['carts_served']} done"
        f" · {live['carts_left_early']} left early",
    ]
    rendered = [font.render(t, True, _TEXT) for t in lines]
    w = max(r.get_width() for r in rendered) + 10
    h = len(rendered) * 14 + 8
    box = pygame.Rect(x, y, w, h)
    pygame.draw.rect(surface, LABEL_BG, box)
    pygame.draw.rect(surface, OUTLINE_COLOR, box, 1)
    ty = y + 4
    for r in rendered:
        surface.blit(r, (x + 5, ty))
        ty += 14
