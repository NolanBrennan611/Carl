"""Bill rules that are pure functions. Phase 1 only needs reminder-offset parsing."""

from __future__ import annotations

import re

from carl.domain.errors import ValidationError

_OFFSETS_RE = re.compile(r"^\s*\d{1,2}(\s*,\s*\d{1,2}){0,4}\s*$")
MAX_OFFSET_DAYS = 60


def parse_offsets(text: str) -> tuple[int, ...]:
    """'7,3,0' -> (7, 3, 0). 1-5 whole numbers, each 0-60, deduplicated, largest first."""
    if not _OFFSETS_RE.match(text):
        raise ValidationError("Reminder days must look like `7,3,0` (up to 5 numbers, 0-60).")
    values = {int(part) for part in text.split(",")}
    if any(v > MAX_OFFSET_DAYS for v in values):
        raise ValidationError(f"Reminder days must be between 0 and {MAX_OFFSET_DAYS}.")
    return tuple(sorted(values, reverse=True))
