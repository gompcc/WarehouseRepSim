# Picker & Product Aisle Model (2026-07-14)

(Previous plan — Environment/Dispatcher separation — is complete; see git
history of this file and results/sim_results.md.)

Goal: add three banks of bi-level picking aisles (per user's sketch), a
2000-SKU catalog with one slot per SKU, SKU-based orders (1–40 lines), and
per-station pickers whose walking time (1.4 m/s + 10 s grab, one SKU line per
round trip, aisles enterable only at the ends) determines cart dwell time at
stations. Full spec: **PRD Section 14**.

Decisions locked with user (2026-07-14):
- Expand grid to 86 cols (+14 west, +12 east), TILE_SIZE 20→16 px
- 1 picker per station (sweepable constant)
- 1.4 m/s walk + 10 s grab, replaces flat PICK_TIME_PER_ITEM=90s
- SKU→station zoning by nearest walking distance

## Plan
- [x] Commit prior session's uncommitted work separately
- [x] Document design in PRD Section 14 + this plan (commit)
- [ ] **Stage 1 — grid expansion**: constants.py (TILE_SIZE 16, GRID_COLS 86,
      all coords +14), map_builder.py (build_map literals, build_graph
      junctions/direction rules, verify_graph tests), renderer label
      positions, cart draw size scaled to tile. Verify: headless 1h run
      before/after gives comparable orders/hr; tests pass. Commit.
- [ ] **Stage 2 — aisles module**: agv_simulation/aisles.py with bank
      geometry (PRD 14.3), exact-2000 slot layout, nearest-station zoning,
      walk path/distance (min over both walkway ends). TileType.AISLE_RACK +
      renderer bars. Snapshot PNG to eyeball vs sketch. Commit.
- [ ] **Stage 3 — pickers + SKU orders**: Order → 1–40 SKU ids with derived
      stations_to_visit; picker.py (per-station FIFO, walk/grab cycle,
      release rule → cart.picking_complete); dispatcher MOVE_TO_PICK /
      PICKING integration; environment tick + stuck-watchdog exemption;
      renderer picker dots; headless + export picker metrics. Commit.
- [ ] **Stage 4 — verify**: pytest, 8h headless run, new snapshot, sanity-check
      walk times (~10–40 m round trips), record results below. Commit.

## Review / Results
(to be filled in as stages complete)
