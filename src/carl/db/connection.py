"""SQLite connection with the pragmas from docs/database-design.md section 1."""

from __future__ import annotations

import asyncio
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
    """Single shared connection. Writes use `transaction()` (BEGIN IMMEDIATE ... COMMIT).

    Everything shares one connection, so two overlapping transactions would tangle together.
    `transaction()` therefore queues: a second caller waits until the first has committed or
    rolled back. Re-entering from the task that already holds it is a bug and raises.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task | None = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        task = asyncio.current_task()
        if task is not None and self._owner is task:
            raise RuntimeError("Nested transactions are not supported")
        async with self._lock:
            self._owner = task
            try:
                await self.conn.execute("BEGIN IMMEDIATE")
                try:
                    yield self.conn
                except BaseException:
                    await self.conn.execute("ROLLBACK")
                    raise
                else:
                    await self.conn.execute("COMMIT")
            finally:
                self._owner = None

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
