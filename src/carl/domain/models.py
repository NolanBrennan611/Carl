"""Plain data types shared across layers. No Discord types here."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    """The authenticated person performing an action."""

    guild_id: int
    user_id: int
    is_admin: bool = False


@dataclass(frozen=True)
class GuildSettings:
    guild_id: int
    timezone: str
    reminder_channel_id: int | None
    reminder_time: str
    default_currency: str
    default_bill_offsets: tuple[int, ...]
    summary_frequency: str
    summary_weekday: int
    summary_time: str
    date_order: str
