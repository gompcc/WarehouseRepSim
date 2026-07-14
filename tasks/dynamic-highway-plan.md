# Dynamic highway pillars — plan (branch: feature/dynamic-highway)

Goal: the left/right highway pillar columns become runtime parameters. Everything
attached to them follows: pick stations S1–S9 + their racking/parking, aisle bank
boundaries (west end / central span / east start), SKU distribution (2000 SKUs
re-spread uniformly over the new aisle lengths), zoning, and walk distances.
GUI: pillars draggable with the mouse (world rebuilds live per column step);
per-station longest pick-walk distance shown on the map.

## Design

New `agv_simulation/layout.py`:
- `HighwayLayout(left_col=23, right_col=52)` frozen dataclass, validated bounds
  (left ≥ 16, right ≤ 70, gap ≥ 17), `move_pillar()` clamped move.
- Derived geometry: `banks` (west 0..L-11, central L+8..R-7, east R+8..84),
  `stations` (9 StationSpecs with station/park/racking cols relative to pillars,
  rows fixed), `sidetrack_cols`.
- Module singleton `get_layout()` / `set_layout()` (same pattern as `_catalog`).

Everything reads the singleton so no signature threading: `build_map()`,
`build_graph()` (junctions + direction rules parameterized), `Catalog`
(banks snapshot + side test + ring distance), `aisle_rack_positions()`,
`astar` sidetrack cols, renderer station labels.

Default layout must produce a **byte-identical** map+graph to today
(golden files: /tmp/golden_tiles.txt, /tmp/golden_graph.txt).

## Checklist
- [x] Worktree `feature/dynamic-highway` off 2bd1f4f
- [x] Golden snapshot of default tiles/graph
- [x] layout.py (HighwayLayout, Bank, StationSpec, singleton)
- [x] aisles.py: layout-aware Catalog, `longest_walk_m()` (max one-way per station)
- [x] map_builder.py: build_map/build_graph/verify_graph from layout
- [x] pathfinding.py: sidetrack cols from layout
- [x] environment.py: `layout=` param
- [x] headless.py: `highway=(l,r)` param, resets singleton per run
- [x] renderer.py: station labels from layout; `≤NNm` longest-walk label per
      station; pillar hover/drag highlight
- [x] __main__.py: mouse drag on pillar columns → clamped set_layout + world
      rebuild (reuses slotting-toggle restart path, factored into a helper)
- [x] Golden diff: default layout identical tiles+graph (1139 tiles, 387
      nodes, 959 edges — byte-identical)
- [x] tests/test_dynamic_highway.py — 17 tests
- [x] Full suite green (109 passed); headless baseline vs main identical
- [x] Review section below

## Review

**Verified:**
- Default layout is byte-identical to the pre-refactor map+graph (golden diff).
- 1h seed-42 headless: main = branch exactly (11 orders, avg cycle 2507.73 s,
  521 picks) — the refactor changes nothing at the default layout.
- Moved layout (18,60), 1h seed 42: 17 orders/hr, 0 teleports — the loop,
  zoning and pickers all work off-default. Notably BETTER than default's 11 —
  highway position is a real throughput lever worth a proper experiment.
- Longest one-way walks respond to geometry: default S7 36.7 m worst;
  spread pillars (18,60) even out to ≤ 28.7 m.
- 109 tests green (17 new). GUI modules import cleanly against the stub.

**Not machine-verified:** the actual mouse-drag feel and the pillar highlight
rendering (needs a human running `python -m agv_simulation`).

**Design notes:** layout is a module singleton mirroring `aisles._catalog`;
Catalog snapshots its layout at build so `set_layout()` can never skew a live
world; the GUI drag reuses the slotting-toggle full-world-restart path
(factored into `restart_world()` in `__main__.main`). `run_headless` resets
the singleton every call so sweeps can't leak a moved layout.
