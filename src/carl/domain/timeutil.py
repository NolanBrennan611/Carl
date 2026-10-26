"""All time-zone and instant conversions live here (see docs/reminder-system.md section 3).

Instants are stored as UTC ISO-8601 text with millisecond precision and a trailing 'Z'.
Calendar dates are local dates in the household time zone.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, available_timezones

from carl.clock import Clock
from carl.domain.errors import ValidationError

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def utc_now(clock: Clock) -> datetime:
    now = clock.now()
    if now.tzinfo is None:
        raise ValueError("Clock returned a naive datetime")
    return now.astimezone(UTC)


def get_zone(tz: str) -> ZoneInfo:
    if tz not in available_timezones():
        raise ValidationError(
            f"`{tz}` isn't a known time zone. Try something like America/Chicago."
        )
    return ZoneInfo(tz)


def local_today(now_utc: datetime, tz: str) -> date:
    return now_utc.astimezone(get_zone(tz)).date()


def parse_hhmm(value: str) -> time:
    match = _HHMM.match(value.strip())
    if not match:
        raise ValidationError("Time must look like HH:MM in 24-hour format, e.g. 08:30.")
    return time(int(match.group(1)), int(match.group(2)))


def local_to_utc(d: date, t: time, tz: str) -> datetime:
    """Local date+time to a UTC instant. fold=0 always.

    - Nonexistent time (spring-forward gap): resolves using the pre-transition offset, so it
      lands just after the gap.
    - Ambiguous time (fall-back): resolves to the first occurrence.
    """
    local = datetime(
        d.year, d.month, d.day, t.hour, t.minute, t.second, tzinfo=get_zone(tz), fold=0
    )
    return local.astimezone(UTC)


def start_of_local_day_utc(d: date, tz: str) -> datetime:
    return local_to_utc(d, time(0, 0), tz)


def to_db_instant(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("Naive datetime can't be stored")
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def from_db_instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
