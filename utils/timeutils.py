
from __future__ import annotations
from datetime import datetime, timezone, timedelta

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def parse_iso(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.fromisoformat(s.replace("Z","+00:00"))

def start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)

def start_of_week(dt: datetime) -> datetime:
    sod = start_of_day(dt)
    return sod - timedelta(days=sod.weekday())

def start_of_month(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

def start_of_year(dt: datetime) -> datetime:
    return dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
