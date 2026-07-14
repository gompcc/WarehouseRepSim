"""GUI layer for the shadow-mode pickers: walking dots + assumptions box.

Kept in its own module so the hookup into the shared ``renderer.render()``
is two lines — the picker subsystem stays independent (PRD §14.9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from .constants import (
    TILE_SIZE, PICKER_WALK_SPEED,
    LABEL_BG, OUTLINE_COLOR,
)
from .models import Order
from .picker import Picker

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
    """Live picker stats (updated every frame), corner above the west bank.

    Both distribution lines are LIVE, computed from the run so far — the
    pick-cycle stats from picks the orders actually demanded (the order
    decides which slot each picker walks to), the lines/order stats from
    every order created so far. No static calibration set pieces."""
    live = manager.stats()
    sizes = Order.sizes
    if sizes:
        lo_mean = sum(sizes) / len(sizes)
        lo_var = sum((s - lo_mean) ** 2 for s in sizes) / len(sizes)
        lines_order = (
            f"lines/order so far: μ{lo_mean:.1f} σ{lo_var ** 0.5:.1f}"
            f" ({len(sizes)} orders)"
        )
    else:
        lines_order = "lines/order so far: — (no orders yet)"
    if live["picks_done"]:
        pick_cycle = (
            f"pick cycle so far: μ{live['walk_mean_s']:.1f}s"
            f" σ{live['walk_sd_s']:.1f}s ({live['picks_done']} picks)"
        )
    else:
        pick_cycle = "pick cycle so far: — (no picks yet)"
    lines = [
        f"PICKERS ({manager.strategy}"
        f"{', gating' if manager.gating else ', shadow'})",
        f"{len(manager.all_pickers())} pickers (click a station to add)"
        f" · {PICKER_WALK_SPEED} m/s",
        lines_order,
        pick_cycle,
        f"busy {live['busy_fraction']:.0%}"
        f" · {live['lines_per_picker_hr']:.0f} lines/picker/hr"
        f" · carts: {live['carts_served']} done"
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
