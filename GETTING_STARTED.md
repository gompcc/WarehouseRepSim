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
   python agv_simulation.py
   ```

## 🎮 Controls

| Key | Action |
|-----|--------|
| `C` | Spawn a new cart |
| `A` | Spawn a new AGV |
| `↑` | Increase simulation speed |
| `↓` | Decrease simulation speed |
| `Space` | Pause/Resume |
| `T` | Toggle auto-cart spawning (1 per 30 seconds) |
| `R` | Reset simulation |
| `Q` | Quit |

## 📊 What You'll See

- **Map Canvas** - Warehouse layout with highways, pick stations, Box Depot, and Pack-off
- **AGVs** (orange squares) - Moving carts through the system
- **Carts** - Color-coded by state:
  - White = Empty
  - Green = Active (has order, picking)
  - Blue = Completed (ready for pack-off)
- **Metrics Panel** - Real-time stats on capacity, throughput, bottlenecks

## 🏗️ Development Phases

This project is built in stages:

1. **Phase 1** - Static map display ✓
2. **Phase 2** - Single AGV movement ✓
3. **Phase 3** - Cart spawning and AGV-cart interaction ✓
4. **Phase 4** - Complete cart lifecycle (MVP) ✓
5. **Phase 5** - Multiple AGVs and job dispatcher ✓
6. **Phase 6** - Capacity-based routing ✓
7. **Phase 7** - Metrics UI and controls ✓
8. **Phase 8+** - Optimization features (optional)

## 📖 Documentation

- **Full Specification**: See `AGV_Warehouse_Simulation_PRD.md`
- **Quick Reference**: See `AGV_Quick_Reference.md`

## 🧪 Testing

### Basic Test (MVP)
1. Press `A` to spawn one AGV
2. Press `C` to spawn one cart
3. Watch the complete lifecycle:
   - AGV picks up cart from spawn zone
   - Takes cart to Box Depot (45s loading)
   - Takes cart to required pick stations (30s per item)
   - Takes cart to Pack-off (60s unloading)
   - Returns empty cart to Box Depot for new order
   - Cycle repeats

### Bottleneck Test
1. Press `T` to enable auto-spawning
2. Press `A` three times to spawn 3 AGVs
3. Run simulation for 10-15 minutes
4. Observe Pack-off bottleneck (carts waiting)
5. Check metrics panel for alerts

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

## 🐛 Known Limitations (Phase 1-7)

- AGVs pass through each other (no collision detection)
- No battery/charging system
- S-zones are unidirectional (bidirectional movement deferred)
- No overtaking on highway
- First-available job assignment (not proximity-based)

These are intentional simplifications for MVP. They can be added in Phase 8+.

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
├── AGV_Warehouse_Simulation_PRD.md      # Full specification
├── AGV_Quick_Reference.md               # Quick lookup guide
├── GETTING_STARTED.md                   # This file
├── requirements.txt                     # Python dependencies
└── phases/                              # Phase backups (optional)
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

**Version 1.0** - January 26, 2026