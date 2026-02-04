from enum import Enum


class TileType(Enum):
    EMPTY        = "empty"
    HIGHWAY      = "highway"        # Blue circles - AGV travel path
    PARKING      = "parking"        # White squares - temp cart storage
    PICK_STATION = "pick_station"   # Yellow - cart dwell spots at stations
    BOX_DEPOT    = "box_depot"      # Brown  - order loading area
    PACKOFF      = "packoff"        # Purple - pack-off conveyor
    AGV_SPAWN    = "agv_spawn"      # Gray   - AGV starting area
    CART_SPAWN   = "cart_spawn"     # Light purple - cart starting area
    RACKING      = "racking"        # Light yellow - shelving / pallet storage


class AGVState(Enum):
    IDLE               = "idle"
    MOVING             = "moving"
    RETURNING_TO_SPAWN = "returning_to_spawn"
    MOVING_TO_PICKUP   = "moving_to_pickup"
    PICKING_UP         = "picking_up"
    MOVING_TO_DROPOFF  = "moving_to_dropoff"
    DROPPING_OFF       = "dropping_off"


class CartState(Enum):
    SPAWNED              = "spawned"                # At spawn zone
    IN_TRANSIT           = "in_transit"             # Being carried by AGV
    IDLE                 = "idle"                   # Dropped off, waiting
    # Phase 4+ lifecycle states:
    TO_BOX_DEPOT         = "to_box_depot"
    AT_BOX_DEPOT         = "at_box_depot"
    IN_TRANSIT_TO_PICK   = "in_transit_to_pick"
    PICKING              = "picking"
    IN_TRANSIT_TO_PACKOFF = "in_transit_to_packoff"
    AT_PACKOFF           = "at_packoff"
    WAITING_FOR_STATION  = "waiting_for_station"  # buffered, waiting for a full station
    COMPLETED            = "completed"


class JobType(Enum):
    PICKUP_TO_BOX_DEPOT = "pickup_to_box_depot"
    MOVE_TO_PICK        = "move_to_pick"
    MOVE_TO_PACKOFF     = "move_to_packoff"
    RETURN_TO_BOX_DEPOT = "return_to_box_depot"
    MOVE_TO_BUFFER      = "move_to_buffer"        # free a full station tile
