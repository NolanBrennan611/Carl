"""grocery_items persistence. Every query is scoped by guild_id. SQL only; no business rules."""

from __future__ import annotations

from collections.abc import Sequence

from carl.db.connection import Database
from carl.domain.models import GroceryItem


def _to_item(row) -> GroceryItem:
    return GroceryItem(
        id=row["id"],
        guild_id=row["guild_id"],
        name=row["name"],
        name_normalized=row["name_normalized"],
        quantity=row["quantity"],
        unit=row["unit"],
        unit_normalized=row["unit_normalized"],
        category=row["category"],
        note=row["note"],
        status=row["status"],
        added_by_user_id=row["added_by_user_id"],
        purchased_by_user_id=row["purchased_by_user_id"],
        purchased_at=row["purchased_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class GroceryRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def insert(
        self,
        *,
        guild_id: int,
        name: str,
        name_normalized: str,
        quantity: float | None,
        unit: str | None,
        unit_normalized: str,
        category: str,
        note: str | None,
        added_by_user_id: int,
        now: str,
    ) -> int:
        cur = await self.db.conn.execute(
            "INSERT INTO grocery_items (guild_id, name, name_normalized, quantity, unit,"
            " unit_normalized, category, note, status, added_by_user_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'needed', ?, ?, ?)",
            (
                guild_id,
                name,
                name_normalized,
                quantity,
                unit,
                unit_normalized,
                category,
                note,
                added_by_user_id,
                now,
                now,
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid

    async def get(self, guild_id: int, item_id: int) -> GroceryItem | None:
        cur = await self.db.conn.execute(
            "SELECT * FROM grocery_items WHERE guild_id = ? AND id = ?", (guild_id, item_id)
        )
        row = await cur.fetchone()
        return _to_item(row) if row else None

    async def find_needed_by_key(
        self, guild_id: int, name_normalized: str, unit_normalized: str
    ) -> GroceryItem | None:
        cur = await self.db.conn.execute(
            "SELECT * FROM grocery_items WHERE guild_id = ? AND name_normalized = ?"
            " AND unit_normalized = ? AND status = 'needed'",
            (guild_id, name_normalized, unit_normalized),
        )
        row = await cur.fetchone()
        return _to_item(row) if row else None

    async def find_needed_by_name(self, guild_id: int, name_normalized: str) -> list[GroceryItem]:
        cur = await self.db.conn.execute(
            "SELECT * FROM grocery_items WHERE guild_id = ? AND name_normalized = ?"
            " AND status = 'needed' ORDER BY id",
            (guild_id, name_normalized),
        )
        return [_to_item(r) for r in await cur.fetchall()]

    async def find_by_name(
        self, guild_id: int, name_normalized: str, status: str | None
    ) -> list[GroceryItem]:
        sql = "SELECT * FROM grocery_items WHERE guild_id = ? AND name_normalized = ?"
        args: list[object] = [guild_id, name_normalized]
        if status:
            sql += " AND status = ?"
            args.append(status)
        cur = await self.db.conn.execute(sql + " ORDER BY id", args)
        return [_to_item(r) for r in await cur.fetchall()]

    async def list_for_guild(
        self, guild_id: int, status: str | None = None, category: str | None = None
    ) -> list[GroceryItem]:
        sql = "SELECT * FROM grocery_items WHERE guild_id = ?"
        args: list[object] = [guild_id]
        if status:
            sql += " AND status = ?"
            args.append(status)
        if category:
            sql += " AND category = ?"
            args.append(category)
        cur = await self.db.conn.execute(sql + " ORDER BY name_normalized, id", args)
        return [_to_item(r) for r in await cur.fetchall()]

    async def search(
        self, guild_id: int, text: str, status: str | None, limit: int
    ) -> list[GroceryItem]:
        sql = "SELECT * FROM grocery_items WHERE guild_id = ?"
        args: list[object] = [guild_id]
        if status:
            sql += " AND status = ?"
            args.append(status)
        if text:
            sql += " AND (name_normalized LIKE ? ESCAPE '\\' OR lower(name) LIKE ? ESCAPE '\\')"
            pattern = f"%{_like_escape(text.casefold())}%"
            args += [pattern, pattern]
        sql += " ORDER BY (status = 'needed') DESC, name_normalized, id LIMIT ?"
        args.append(limit)
        cur = await self.db.conn.execute(sql, args)
        return [_to_item(r) for r in await cur.fetchall()]

    async def counts(self, guild_id: int) -> tuple[int, int]:
        """(needed, purchased)."""
        cur = await self.db.conn.execute(
            "SELECT"
            " coalesce(sum(status = 'needed'), 0) AS needed,"
            " coalesce(sum(status = 'purchased'), 0) AS purchased"
            " FROM grocery_items WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cur.fetchone()
        return int(row["needed"]), int(row["purchased"])

    async def update_content(
        self,
        *,
        guild_id: int,
        item_id: int,
        name: str,
        name_normalized: str,
        quantity: float | None,
        unit: str | None,
        unit_normalized: str,
        category: str,
        note: str | None,
        now: str,
    ) -> None:
        await self.db.conn.execute(
            "UPDATE grocery_items SET name = ?, name_normalized = ?, quantity = ?, unit = ?,"
            " unit_normalized = ?, category = ?, note = ?, updated_at = ?"
            " WHERE guild_id = ? AND id = ?",
            (
                name,
                name_normalized,
                quantity,
                unit,
                unit_normalized,
                category,
                note,
                now,
                guild_id,
                item_id,
            ),
        )

    async def mark_purchased(self, guild_id: int, item_id: int, user_id: int, now: str) -> bool:
        cur = await self.db.conn.execute(
            "UPDATE grocery_items SET status = 'purchased', purchased_by_user_id = ?,"
            " purchased_at = ?, updated_at = ? WHERE guild_id = ? AND id = ? AND status = 'needed'",
            (user_id, now, now, guild_id, item_id),
        )
        return cur.rowcount == 1

    async def mark_needed(self, guild_id: int, item_id: int, now: str) -> bool:
        cur = await self.db.conn.execute(
            "UPDATE grocery_items SET status = 'needed', purchased_by_user_id = NULL,"
            " purchased_at = NULL, updated_at = ? WHERE guild_id = ? AND id = ?"
            " AND status = 'purchased'",
            (now, guild_id, item_id),
        )
        return cur.rowcount == 1

    async def delete(self, guild_id: int, item_id: int) -> bool:
        cur = await self.db.conn.execute(
            "DELETE FROM grocery_items WHERE guild_id = ? AND id = ?", (guild_id, item_id)
        )
        return cur.rowcount == 1

    async def delete_purchased(self, guild_id: int) -> int:
        cur = await self.db.conn.execute(
            "DELETE FROM grocery_items WHERE guild_id = ? AND status = 'purchased'", (guild_id,)
        )
        return cur.rowcount

    async def get_many(self, guild_id: int, ids: Sequence[int]) -> list[GroceryItem]:
        if not ids:
            return []
        marks = ", ".join("?" for _ in ids)
        cur = await self.db.conn.execute(
            f"SELECT * FROM grocery_items WHERE guild_id = ? AND id IN ({marks})",
            [guild_id, *ids],
        )
        return [_to_item(r) for r in await cur.fetchall()]
