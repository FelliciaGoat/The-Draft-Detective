"""Create tables and (optionally) seed demo data.

Run manually:
    python -m app.database.init_db            # create tables
    python -m app.database.init_db --seed     # create tables + demo room "Room A-101"

For a real production system use Alembic migrations instead of `create_all`.
"""

import argparse
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registers the models on Base.metadata)
from app.core.config import get_settings
from app.core.enums import SensorType
from app.core.logging_config import setup_logging
from app.database.database import Base, SessionLocal, engine
from app.models.room import Room
from app.models.sensor import Sensor

logger = logging.getLogger(__name__)

DEMO_DEVICE_ID = "ESP32-A101"


def init_db() -> None:
    """Create all tables that do not exist yet."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables are ready")


def seed_demo_data(db: Session) -> bool:
    """Insert the demo room and its sensors if the database has no rooms. Returns True if seeded."""
    if db.scalar(select(func.count()).select_from(Room)):
        return False
    room = Room(
        name="Room A-101",
        building="Main Building",
        floor=1,
        zone="North Wing",
        climate_zone="Composite",
    )
    db.add(room)
    db.flush()
    for sensor_type in (SensorType.ACOUSTIC, SensorType.ROOM_TEMPERATURE, SensorType.EDGE_TEMPERATURE):
        db.add(Sensor(room_id=room.id, sensor_type=sensor_type.value, device_id=DEMO_DEVICE_ID))
    db.commit()
    logger.info("Seeded demo room '%s' (id=%s)", room.name, room.id)
    return True


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Initialise the database.")
    parser.add_argument("--seed", action="store_true", help="also create the demo room")
    args = parser.parse_args()
    setup_logging(get_settings().log_level)
    init_db()
    if args.seed:
        with SessionLocal() as db:
            seeded = seed_demo_data(db)
        print("Demo data created." if seeded else "Rooms already exist; nothing seeded.")


if __name__ == "__main__":
    main()
