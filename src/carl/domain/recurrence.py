"""Recurrence rules (docs/database-design.md section 5).

All occurrences are computed from the anchor, never from the previous occurrence, so month-end
clamping can't drift (Jan 31 -> Feb 28 -> Mar 31).
"""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, timedelta

from carl.domain.errors import ValidationError

FREQS = ("daily", "weekly", "monthly", "yearly")
MAX_RESULTS = 400


@dataclass(frozen=True)
class Rule:
    freq: str
    interval: int
    anchor: date
    monthday: str = "anchor"  # "anchor" or "last" (monthly only)
    until: date | None = None
    v: int = 1


# Slash-command `repeat` choice -> (freq, interval, monthday)
REPEAT_CHOICES: dict[str, tuple[str, int, str]] = {
    "daily": ("daily", 1, "anchor"),
    "weekly": ("weekly", 1, "anchor"),
    "biweekly": ("weekly", 2, "anchor"),
    "monthly": ("monthly", 1, "anchor"),
    "monthly_last_day": ("monthly", 1, "last"),
    "quarterly": ("monthly", 3, "anchor"),
    "yearly": ("yearly", 1, "anchor"),
}


def from_choice(choice: str, anchor: date, repeat_every: int | None = None) -> Rule | None:
    """Build a rule from the `repeat` / `repeat_every` command options. 'none' -> None."""
    if choice == "none":
        return None
    if choice not in REPEAT_CHOICES:
        raise ValidationError(f"Unknown repeat option `{choice}`.")
    freq, interval, monthday = REPEAT_CHOICES[choice]
    if repeat_every is not None:
        if not 1 <= repeat_every <= 12:
            raise ValidationError("Repeat every must be between 1 and 12.")
        interval *= repeat_every
    return Rule(freq=freq, interval=interval, anchor=anchor, monthday=monthday)


def to_json(rule: Rule) -> str:
    return json.dumps(
        {
            "v": rule.v,
            "freq": rule.freq,
            "interval": rule.interval,
            "anchor": rule.anchor.isoformat(),
            "monthday": rule.monthday,
            "until": rule.until.isoformat() if rule.until else None,
        },
        separators=(",", ":"),
    )


def parse(raw: str) -> Rule:
    try:
        data = json.loads(raw)
        if data["v"] != 1:
            raise ValidationError("Unsupported recurrence version.")
        freq = data["freq"]
        interval = int(data["interval"])
        anchor = date.fromisoformat(data["anchor"])
        monthday = data.get("monthday", "anchor")
        until = date.fromisoformat(data["until"]) if data.get("until") else None
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationError("Invalid recurrence rule.") from exc
    if freq not in FREQS:
        raise ValidationError("Invalid recurrence frequency.")
    if not 1 <= interval <= 52:
        raise ValidationError("Recurrence interval must be between 1 and 52.")
    if monthday not in ("anchor", "last"):
        raise ValidationError("Invalid month-day rule.")
    if monthday == "last" and freq != "monthly":
        raise ValidationError("'last day' only applies to monthly recurrence.")
    return Rule(freq=freq, interval=interval, anchor=anchor, monthday=monthday, until=until)


def _add_months(anchor: date, months: int, monthday: str) -> date:
    total = anchor.year * 12 + (anchor.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    day = last if monthday == "last" else min(anchor.day, last)
    return date(year, month, day)


def occurrence(rule: Rule, k: int) -> date | None:
    """The k-th occurrence (k=0 is the anchor). None if past `until` or beyond year 9999."""
    if k < 0:
        raise ValueError("k must be >= 0")
    try:
        if rule.freq == "daily":
            d = rule.anchor + timedelta(days=k * rule.interval)
        elif rule.freq == "weekly":
            d = rule.anchor + timedelta(days=7 * k * rule.interval)
        elif rule.freq == "monthly":
            d = _add_months(rule.anchor, k * rule.interval, rule.monthday)
        else:  # yearly
            year = rule.anchor.year + k * rule.interval
            last = calendar.monthrange(year, rule.anchor.month)[1]
            d = date(year, rule.anchor.month, min(rule.anchor.day, last))
    except (OverflowError, ValueError):
        return None
    if rule.until is not None and d > rule.until:
        return None
    return d


def _first_k_on_or_after(rule: Rule, target: date) -> int:
    """Smallest k whose occurrence is >= target (ignores `until`)."""
    if target <= rule.anchor:
        return 0
    # Estimate k from elapsed time, then walk to the exact boundary.
    days = (target - rule.anchor).days
    if rule.freq == "daily":
        k = days // rule.interval
    elif rule.freq == "weekly":
        k = days // (7 * rule.interval)
    elif rule.freq == "monthly":
        months = (target.year - rule.anchor.year) * 12 + (target.month - rule.anchor.month)
        k = max(0, months // rule.interval - 1)
    else:
        k = max(0, (target.year - rule.anchor.year) // rule.interval - 1)
    while True:
        d = occurrence(rule, k)
        if d is None:
            # Past `until`/overflow; callers treat any result beyond the end as "none".
            return k
        if d >= target:
            return k
        k += 1


def next_on_or_after(rule: Rule, d: date) -> date | None:
    k = _first_k_on_or_after(rule, d)
    return occurrence(rule, k)


def next_after(rule: Rule, d: date) -> date | None:
    return next_on_or_after(rule, d + timedelta(days=1))


def between(rule: Rule, start: date, end_inclusive: date) -> list[date]:
    """Occurrences with start <= date <= end_inclusive, capped at 400 results."""
    out: list[date] = []
    if end_inclusive < start:
        return out
    k = _first_k_on_or_after(rule, start)
    while len(out) < MAX_RESULTS:
        d = occurrence(rule, k)
        if d is None or d > end_inclusive:
            break
        out.append(d)
        k += 1
    return out
