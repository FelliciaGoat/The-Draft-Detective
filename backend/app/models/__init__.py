"""Import all models so SQLAlchemy registers them on `Base.metadata`."""

from app.models.reading import RoomAnalytics, SensorReading
from app.models.room import Room
from app.models.sensor import Sensor

__all__ = ["Room", "Sensor", "SensorReading", "RoomAnalytics"]
