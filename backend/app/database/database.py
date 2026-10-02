"""Database engine, session factory and declarative base.

SQLite is used in development, PostgreSQL in production. Only the DATABASE_URL changes;
no model code is SQLite-specific.
"""

import logging
from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class UTCDateTime(TypeDecorator):
    """DateTime column that always stores naive UTC and always returns aware UTC.

    SQLite (and PostgreSQL 'timestamp without time zone') drop timezone info. This wrapper makes
    sure the API always emits ISO strings ending in `Z`/`+00:00`, so a JavaScript frontend never
    mistakes them for local time.
    """

    impl = DateTime(timezone=False)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        """Convert to naive UTC before writing."""
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        """Attach the UTC timezone after reading."""
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def _make_engine(database_url: str) -> Engine:
    """Create the SQLAlchemy engine with sensible per-database options."""
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=not is_sqlite,
        future=True,
    )

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
            """Enable foreign keys (for ON DELETE CASCADE) and WAL (readers + a writer at once)."""
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


engine: Engine = _make_engine(get_settings().database_url)

# expire_on_commit=False lets us keep using objects (e.g. to build a WebSocket message)
# right after commit without triggering extra queries.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield one database session per request and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
