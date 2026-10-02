"""Small time helpers. Everything inside the backend is timezone-aware UTC."""

from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Convert any datetime to aware UTC. Naive datetimes are assumed to already be UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def local_day_start(now: datetime, offset_minutes: int = 0) -> datetime:
    """Start of the current 'dashboard day' (as UTC) for a fixed UTC offset.

    Example: offset 330 (India). At 2026-09-29 10:00 UTC it is 15:30 local, so the local day
    started at 2026-09-28 18:30 UTC.
    """
    offset = timedelta(minutes=offset_minutes)
    local_now = ensure_utc(now) + offset
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight - offset


def local_month_start(now: datetime, offset_minutes: int = 0) -> datetime:
    """Start of the current 'dashboard month' (as UTC) for a fixed UTC offset."""
    offset = timedelta(minutes=offset_minutes)
    local_now = ensure_utc(now) + offset
    local_first = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return local_first - offset
