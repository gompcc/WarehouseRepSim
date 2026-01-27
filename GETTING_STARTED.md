# AGV Warehouse Simulation

Discrete-event simulation of an automated warehouse system with AGVs (Automated Guided Vehicles) and picking carts.

## 🎯 Project Goal

Simulate a real warehouse AGV system to:
- Identify bottlenecks
- Test optimization scenarios
- Measure throughput metrics
- Optimize AGV fleet size and routing logic

## 📋 Requirements

- Python 3.8 or higher
- Pygame library

## 🚀 Setup

1. **Install Python** (if not already installed)
   ```bash
   # Check Python version
   python --version  # Should be 3.8+
   ```

2. **Install Pygame**
   ```bash
   pip install pygame
   ```

3. **Download Project Files**
   - `agv_simulation.py` - Main simulation file
   - `AGV_Warehouse_Simulation_PRD.md` - Full specification
   - `AGV_Quick_Reference.md` - Quick lookup guide
   - Reference warehouse image

4. **Run the Simulation**
   ```bash
   source venv/bin/activate && python3 agv_simulation.py
   ```

## 🎮 Controls

| Key | Action |
|-----|--------|
| `A` | Spawn a new AGV |
| `C` | Spawn a new cart |
| `P` | Selected AGV picks up nearest cart |
| `R` | Selected AGV returns to spawn |
| `TAB` | Cycle selected AGV |
| `D` | Debug dump (print all status) |
| `↑` | Increase simulation speed (×2, max 64×) |
| `↓` | Decrease simulation speed (÷2, min 0.25×) |
| `Q` / `ESC` | Quit |
| Left Click | Send selected AGV to clicked tile |

## 📊 What You'll See

- **Map Canvas** - Warehouse layout with highways, pick stations, Box Depot, and Pack-off
- **AGVs** (red circles) - Moving carts through the system
- **Carts** - Color-coded by state:
  - White = Spawned (at spawn zone)
  - Green = In transit (being carried)
  - Orange = Processing (at station)
  - Red = Completed
  - Blue = Idle (waiting for pickup)
- **Status Bar** - Real-time info displayed at the bottom of the window

## 🏗️ Development Phases

This project is built in stages:

1. **Phase 1** - Static map display ✅
2. **Phase 2** - Single AGV movement ✅
3. **Phase 3** - Cart spawning and AGV-cart interaction ✅
4. **Phase 4** - Complete cart lifecycle (MVP) ✅
5. **Phase 5** - Multiple AGVs and job dispatcher ✅
6. **Phase 5b** - Collision avoidance & highway preference ✅
7. **Phase 6** - Capacity-based routing
8. **Phase 7** - Metrics UI and controls
9. **Phase 8+** - Optimization features (optional)

## 📖 Documentation

- **Full Specification**: See `AGV_Warehouse_Simulation_PRD.md`
- **Quick Reference**: See `AGV_Quick_Reference.md`

## 🧪 Testing

### Automated Tests
```bash
source venv/bin/activate && pytest test_collision_avoidance.py -v
```
11 tests covering: A* highway preference, blocked tiles, collision avoidance, rerouting, spawn guard, and multi-AGV overlap detection.

### Manual Test (MVP)
1. Press `A` to spawn one AGV
2. Press `C` to spawn one cart
3. Watch the complete lifecycle:
   - AGV picks up cart from spawn zone
   - Takes cart to Box Depot (45s loading)
   - Takes cart to required pick stations (30s per item)
   - Takes cart to Pack-off (60s unloading)
   - Returns empty cart to Box Depot for new order
   - Cycle repeats

### Stress Test
1. Press `A` multiple times to spawn 3-5 AGVs
2. Press `C` multiple times to spawn 3-4 carts
3. Increase speed with `↑` to 16× or 32×
4. Observe collision avoidance (AGVs reroute around each other)
5. Press `D` to see detailed debug dump

## 🔧 Troubleshooting

### Simulation runs too fast/slow
- Use arrow keys to adjust speed (try 2x or 5x)
- Check that timing constants match PRD specification

### AGVs not moving
- Check console for error messages
- Verify pathfinding is working (AGV should have a path)
- Check AGV state (should be MOVING when traveling)

### Carts not getting orders
- Verify cart reaches Box Depot
- Check dwell timer is counting down
- Ensure order generation function is working

### Map doesn't match reference image
- Review Phase 1 implementation
- Manually verify tile coordinates
- Check station positions and capacities

## 📈 Optimization Experiments

Once the simulation is working, try these scenarios:

### Vary AGV Count
```python
# Test with different fleet sizes
for num_agvs in [3, 5, 8, 10, 15]:
    # Run simulation, measure throughput
    # Find optimal AGV count
```

### Test Pack-off Capacity
```python
# Change Pack-off capacity
STATION_CAPACITIES["Pack_off"] = 6  # Instead of 4
# Measure improvement in throughput
```

### Compare Job Assignment Strategies
```python
# A/B test:
# Mode 1: First available AGV
# Mode 2: Nearest AGV
# Measure: Average cart cycle time, AGV travel distance
```

## 🐛 Known Limitations

- No capacity-based routing yet (all stations treated equally)
- No metrics panel / throughput tracking
- No pause functionality
- No auto-cart spawning toggle
- No battery/charging system
- S-zones are unidirectional (bidirectional movement deferred)
- First-available job assignment (not proximity-based)

These are intentional simplifications. They can be added in future phases.

## 📝 Making Changes

If you want to modify the simulation:

1. **Check the PRD first** - Ensure your change doesn't conflict with specification
2. **Update PRD if needed** - Keep it as single source of truth
3. **Test thoroughly** - Verify the change doesn't break existing functionality
4. **Document changes** - Update comments and this README

## 🤝 Using Claude Code

When asking Claude Code for help:

1. **Reference the PRD**: "See AGV_Warehouse_Simulation_PRD.md, Phase X"
2. **Be specific**: "The AGV doesn't stop at destination" (not "it doesn't work")
3. **Provide context**: Share relevant code sections
4. **State current phase**: "I'm working on Phase 4, don't add Phase 5 features yet"

## 📚 Learning Resources

- Pygame documentation: https://www.pygame.org/docs/
- A* pathfinding: https://en.wikipedia.org/wiki/A*_search_algorithm
- Discrete-event simulation: https://en.wikipedia.org/wiki/Discrete-event_simulation

## 🎓 Project Structure

```
agv_warehouse_simulation/
├── agv_simulation.py                    # Main simulation file
├── test_collision_avoidance.py          # Pytest test suite (11 tests)
├── AGV_Warehouse_Simulation_PRD.md      # Full specification
├── AGV_Quick_Reference.md               # Quick lookup guide
├── GETTING_STARTED.md                   # This file
├── requirements.txt                     # Python dependencies
└── phases/                              # Phase backups
    ├── phase1_static_map.py
    ├── phase2_agv_movement.py
    └── ...
```

## ✨ Success Criteria

You'll know it's working when:
- ✅ Carts complete full lifecycle autonomously
- ✅ Multiple AGVs work simultaneously without conflicts
- ✅ Pack-off bottleneck appears (matching real warehouse)
- ✅ Metrics accurately reflect system state
- ✅ Can run for extended periods without crashes

## 🎉 Next Steps

1. **Start with Phase 1**: Get the static map rendering
2. **Test each phase**: Don't move forward until current phase works
3. **Reference the PRD**: It's your single source of truth
4. **Ask questions**: Use Claude Code with specific queries

Good luck! 🚀

---

**Version 2.0** - January 27, 2026