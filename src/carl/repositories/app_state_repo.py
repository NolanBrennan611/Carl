"""Small key/value store for runtime state (command hash, last backup, ...)."""

from __future__ import annotations

from carl.db.connection import Database


class AppStateRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get(self, key: str) -> str | None:
        cur = await self.db.conn.execute("SELECT value FROM app_state WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else None

    async def set(self, key: str, value: str, now: str) -> None:
        await self.db.conn.execute(
            "INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET"
            " value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now),
        )
