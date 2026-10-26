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
class GroceryItem:
    id: int
    guild_id: int
    name: str
    name_normalized: str
    quantity: float | None
    unit: str | None
    unit_normalized: str
    category: str
    note: str | None
    status: str  # 'needed' | 'purchased'
    added_by_user_id: int
    purchased_by_user_id: int | None
    purchased_at: str | None
    created_at: str
    updated_at: str


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
