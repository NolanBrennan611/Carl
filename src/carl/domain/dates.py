"""Date-expression parser (docs/discord-commands.md section 7).

Pure and deterministic. Relative to `today` in the household zone.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from carl.domain.errors import ValidationError

_WEEKDAYS = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
}  # fmt: skip
_MONTHS = (
    {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
    | {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
    | {"sept": 9}
)

_REL_SHORT = re.compile(r"^\+(\d{1,4})([dwm])$")
_REL_LONG = re.compile(r"^in\s+(\d{1,4})\s+(day|days|week|weeks|month|months)$")
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_NUMERIC = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?$")
_MON_DAY = re.compile(r"^([a-z]+)\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?$")
_DAY_MON = re.compile(r"^(\d{1,2})\s+([a-z]+)\.?(?:,?\s+(\d{4}))?$")

MAX_YEARS = 10

HELP = "Try `tomorrow`, `fri`, `11/5`, `2026-11-05`, or `+3d`."


def add_months(d: date, months: int) -> date:
    """Add calendar months, clamping to month end."""
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _bad(text: str) -> ValidationError:
    return ValidationError(f"I couldn't understand `{text}`. {HELP}")


def _build(year: int, month: int, day: int, original: str) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise _bad(original) from exc


def _next_occurrence_of(month: int, day: int, today: date, original: str) -> date:
    """Year omitted -> the next such date on or after today."""
    for year in range(today.year, today.year + 9):  # 9 years always spans a leap-day gap
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    raise _bad(original)


def parse_date(text: str, today: date, date_order: str = "MDY") -> date:
    original = text
    s = text.strip().lower()
    if not s:
        raise _bad(original)

    result = _parse(s, today, date_order, original)
    limit = date(today.year + MAX_YEARS, today.month, min(today.day, 28))
    lower = date(today.year - MAX_YEARS, today.month, min(today.day, 28))
    if result > limit or result < lower:
        raise ValidationError("That date is more than 10 years away. Please check it.")
    return result


def _parse(s: str, today: date, date_order: str, original: str) -> date:
    if s == "today":
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    if s == "next week":
        return today + timedelta(days=7 - today.weekday())
    if s in _WEEKDAYS:
        ahead = (_WEEKDAYS[s] - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)

    m = _REL_SHORT.match(s)
    if m:
        return _relative(
            int(m.group(1)), {"d": "day", "w": "week", "m": "month"}[m.group(2)], today
        )
    m = _REL_LONG.match(s)
    if m:
        return _relative(int(m.group(1)), m.group(2).rstrip("s"), today)

    m = _ISO.match(s)
    if m:
        return _build(int(m.group(1)), int(m.group(2)), int(m.group(3)), original)

    m = _NUMERIC.match(s)
    if m:
        first, second, year_s = int(m.group(1)), int(m.group(2)), m.group(3)
        month, day = (first, second) if date_order == "MDY" else (second, first)
        if year_s is None:
            if not (1 <= month <= 12):
                raise _bad(original)
            return _next_occurrence_of(month, day, today, original)
        year = int(year_s)
        if len(year_s) == 2:
            year += 2000
        return _build(year, month, day, original)

    m = _MON_DAY.match(s)
    if m and m.group(1) in _MONTHS:
        month, day, year_s = _MONTHS[m.group(1)], int(m.group(2)), m.group(3)
        if year_s:
            return _build(int(year_s), month, day, original)
        return _next_occurrence_of(month, day, today, original)

    m = _DAY_MON.match(s)
    if m and m.group(2) in _MONTHS:
        month, day, year_s = _MONTHS[m.group(2)], int(m.group(1)), m.group(3)
        if year_s:
            return _build(int(year_s), month, day, original)
        return _next_occurrence_of(month, day, today, original)

    raise _bad(original)


def _relative(n: int, unit: str, today: date) -> date:
    if unit == "day":
        return today + timedelta(days=n)
    if unit == "week":
        return today + timedelta(weeks=n)
    return add_months(today, n)
