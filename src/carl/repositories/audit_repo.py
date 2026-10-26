"""Audit log. Records who did what; never records names, notes, or amounts."""

from __future__ import annotations

import json

from carl.db.connection import Database


class AuditRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def add(
        self,
        *,
        guild_id: int,
        actor_user_id: int | None,
        action: str,
        entity_type: str,
        entity_id: int | None,
        details: dict | None,
        at: str,
    ) -> None:
        await self.db.conn.execute(
            "INSERT INTO audit_log (guild_id, actor_user_id, action, entity_type, entity_id,"
            " details_json, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                actor_user_id,
                action,
                entity_type,
                entity_id,
                json.dumps(details, separators=(",", ":")) if details else None,
                at,
            ),
        )
