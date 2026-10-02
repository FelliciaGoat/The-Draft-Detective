"""Shared enumerations.

They are stored in the database as plain strings (not database ENUM types) so that
switching from SQLite to PostgreSQL never needs an enum migration.
"""

from enum import StrEnum


class SensorType(StrEnum):
    """Kinds of sensors a room can have."""

    ACOUSTIC = "acoustic"
    ROOM_TEMPERATURE = "room_temperature"
    EDGE_TEMPERATURE = "edge_temperature"
    HUMIDITY = "humidity"
    CO2 = "co2"
    POWER = "power"


class SensorStatus(StrEnum):
    """Operational status of a registered sensor."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    FAULT = "fault"


class RoomState(StrEnum):
    """What the system currently believes about a room (never a certainty)."""

    OCCUPIED = "occupied"
    VACANT = "vacant"
    UNCERTAIN = "uncertain"


class RecommendedAction(StrEnum):
    """Recommendation produced by sensor fusion. A human or BMS decides what to do."""

    NORMAL_OPERATION = "normal_operation"
    ENERGY_SAVING_MODE = "energy_saving_mode"
    INSPECT_ENVELOPE = "inspect_envelope"
    MAINTAIN_SAFE_STATE = "maintain_safe_state"
    INSUFFICIENT_DATA = "insufficient_data"


class ReadingSource(StrEnum):
    """How a reading entered the system."""

    REST = "rest"
    MQTT = "mqtt"
    SIMULATION = "simulation"


class SimulationScenario(StrEnum):
    """Scenarios available in simulation mode."""

    OCCUPIED_ROOM = "occupied_room"
    EMPTY_ROOM = "empty_room"
    EMPTY_ROOM_HVAC_ON = "empty_room_hvac_on"
    OCCUPIED_NORMAL_THERMAL = "occupied_normal_thermal"
    THERMAL_ANOMALY = "thermal_anomaly"
    NOISY_ACOUSTIC = "noisy_acoustic"
    DEMO_STORY = "demo_story"
