"""guild_settings persistence. Every query is scoped by guild_id."""

from __future__ import annotations

import json

from carl.db.connection import Database
from carl.domain.models import GuildSettings

_COLUMNS = (
    "guild_id, timezone, reminder_channel_id, reminder_time, default_currency,"
    " default_bill_offsets_json, summary_frequency, summary_weekday, summary_time, date_order"
)


def _row_to_settings(row) -> GuildSettings:
    return GuildSettings(
        guild_id=row["guild_id"],
        timezone=row["timezone"],
        reminder_channel_id=row["reminder_channel_id"],
        reminder_time=row["reminder_time"],
        default_currency=row["default_currency"],
        default_bill_offsets=tuple(json.loads(row["default_bill_offsets_json"])),
        summary_frequency=row["summary_frequency"],
        summary_weekday=row["summary_weekday"],
        summary_time=row["summary_time"],
        date_order=row["date_order"],
    )


class SettingsRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get(self, guild_id: int) -> GuildSettings | None:
        cur = await self.db.conn.execute(
            f"SELECT {_COLUMNS} FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        return _row_to_settings(row) if row else None

    async def insert_if_absent(self, s: GuildSettings, now: str) -> bool:
        """Insert the row if missing. Returns True when a row was created."""
        cur = await self.db.conn.execute(
            "INSERT OR IGNORE INTO guild_settings (guild_id, timezone, reminder_channel_id,"
            " reminder_time, default_currency, default_bill_offsets_json, summary_frequency,"
            " summary_weekday, summary_time, date_order, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                s.guild_id,
                s.timezone,
                s.reminder_channel_id,
                s.reminder_time,
                s.default_currency,
                json.dumps(list(s.default_bill_offsets)),
                s.summary_frequency,
                s.summary_weekday,
                s.summary_time,
                s.date_order,
                now,
                now,
            ),
        )
        return cur.rowcount == 1

    async def update(self, s: GuildSettings, now: str) -> None:
        await self.db.conn.execute(
            "UPDATE guild_settings SET timezone = ?, reminder_channel_id = ?, reminder_time = ?,"
            " default_currency = ?, default_bill_offsets_json = ?, summary_frequency = ?,"
            " summary_weekday = ?, summary_time = ?, date_order = ?, updated_at = ?"
            " WHERE guild_id = ?",
            (
                s.timezone,
                s.reminder_channel_id,
                s.reminder_time,
                s.default_currency,
                json.dumps(list(s.default_bill_offsets)),
                s.summary_frequency,
                s.summary_weekday,
                s.summary_time,
                s.date_order,
                now,
                s.guild_id,
            ),
        )
