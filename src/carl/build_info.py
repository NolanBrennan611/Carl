"""Build-time constants."""

from datetime import UTC, datetime

VERSION = "0.1.0"
# If the system clock reads earlier than this, it is wrong (e.g. a Pi booted without NTP).
MIN_SANE_DATE = datetime(2026, 1, 1, tzinfo=UTC)
