"""Human-readable dates and relative labels."""

from __future__ import annotations

from datetime import date, datetime


def format_date(d: date) -> str:
    """Unambiguous long form: 'Sun, Nov 1, 2026'."""
    return f"{d.strftime('%a, %b')} {d.day}, {d.year}"


def format_date_short(d: date) -> str:
    """'Sun Nov 1'."""
    return f"{d.strftime('%a %b')} {d.day}"


def format_clock(dt: datetime) -> str:
    """'2:14 PM' for a (local) datetime."""
    return dt.strftime("%I:%M %p").lstrip("0")


def relative_days(d: date, today: date) -> str:
    """'today', 'tomorrow', 'in 3 days', 'yesterday', '6 days overdue'."""
    delta = (d - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta > 1:
        return f"in {delta} days"
    if delta == -1:
        return "yesterday"
    return f"{-delta} days overdue"
