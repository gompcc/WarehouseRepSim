"""Shared pytest fixtures — install pygame stub before any test imports."""

from agv_simulation.pygame_stub import install

install()
