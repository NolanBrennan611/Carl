"""SQLite connection with the pragmas from docs/database-design.md section 1."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = FULL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA trusted_schema = OFF",
)


class Database:
    """Single shared connection. Writes use `transaction()` (BEGIN IMMEDIATE ... COMMIT)."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn
        self._in_tx = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        if self._in_tx:
            raise RuntimeError("Nested transactions are not supported")
        self._in_tx = True
        await self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            await self.conn.execute("ROLLBACK")
            raise
        else:
            await self.conn.execute("COMMIT")
        finally:
            self._in_tx = False

    async def close(self) -> None:
        await self.conn.close()


async def open_db(path: Path | str) -> Database:
    path = Path(path) if str(path) != ":memory:" else path
    if isinstance(path, Path):
        path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None -> autocommit; we issue BEGIN/COMMIT ourselves.
    conn = await aiosqlite.connect(path, isolation_level=None)
    conn.row_factory = aiosqlite.Row
    for pragma in PRAGMAS:
        await conn.execute(pragma)
    return Database(conn)
