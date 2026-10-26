"""Migration runner (docs/database-design.md section 9).

Files: migrations/NNNN_name.sql, applied in order, each in one transaction, with a sha256
checksum recorded. An applied migration whose file has changed refuses startup.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from carl.clock import Clock
from carl.db.backup import online_backup
from carl.db.connection import Database
from carl.domain.timeutil import to_db_instant, utc_now

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
FK_OFF_DIRECTIVE = "-- carl:foreign_keys_off"


class MigrationError(Exception):
    """A migration failed, is malformed, or was modified after being applied."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


@dataclass(frozen=True)
class MigrationStatus:
    applied: list[int]
    pending: list[int]


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _NAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"Bad migration file name: {path.name}")
        raw = path.read_bytes()
        migrations.append(
            Migration(
                version=int(match.group(1)),
                name=match.group(2),
                sql=raw.decode("utf-8"),
                checksum=hashlib.sha256(raw).hexdigest(),
            )
        )
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"Migration numbers must be contiguous from 0001, got {versions}")
    return migrations


async def _ensure_table(db: Database) -> None:
    await db.conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL,"
        " checksum TEXT NOT NULL, applied_at TEXT NOT NULL) STRICT"
    )


async def _applied(db: Database) -> dict[int, str]:
    cur = await db.conn.execute("SELECT version, checksum FROM schema_migrations")
    return {row["version"]: row["checksum"] for row in await cur.fetchall()}


async def status(db: Database, directory: Path = MIGRATIONS_DIR) -> MigrationStatus:
    await _ensure_table(db)
    applied = await _applied(db)
    all_versions = [m.version for m in discover(directory)]
    return MigrationStatus(
        applied=sorted(applied),
        pending=[v for v in all_versions if v not in applied],
    )


async def migrate(
    db: Database,
    clock: Clock,
    *,
    db_path: Path | None = None,
    backup_dir: Path | None = None,
    directory: Path = MIGRATIONS_DIR,
) -> list[int]:
    """Apply pending migrations. Returns the versions applied.

    If anything is pending and the database file already has content, a pre-migration backup
    is written to `backup_dir` first.
    """
    migrations = discover(directory)
    await _ensure_table(db)
    applied = await _applied(db)

    for mig in migrations:
        if mig.version in applied and applied[mig.version] != mig.checksum:
            raise MigrationError(
                f"Migration {mig.version:04d}_{mig.name} was modified after being applied. "
                "Never edit an applied migration; add a new one instead."
            )
    known = {m.version for m in migrations}
    unknown = sorted(set(applied) - known)
    if unknown:
        raise MigrationError(
            f"Database has migrations {unknown} that this code doesn't know. "
            "Run a newer version of Carl, or restore an older backup."
        )

    pending = [m for m in migrations if m.version not in applied]
    if not pending:
        return []

    if applied and db_path is not None and backup_dir is not None:
        stamp = utc_now(clock).strftime("%Y%m%dT%H%M%SZ")
        online_backup(db_path, backup_dir / f"pre-migration-{pending[0].version:04d}-{stamp}.db")

    done: list[int] = []
    for mig in pending:
        await _apply(db, mig, to_db_instant(utc_now(clock)))
        done.append(mig.version)
    return done


async def _apply(db: Database, mig: Migration, applied_at: str) -> None:
    fk_off = FK_OFF_DIRECTIVE in mig.sql
    if fk_off:
        await db.conn.execute("PRAGMA foreign_keys = OFF")
    name = mig.name.replace("'", "")
    script = (
        "BEGIN IMMEDIATE;\n"
        f"{mig.sql}\n;"
        "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
        f"VALUES ({mig.version}, '{name}', '{mig.checksum}', '{applied_at}');\n"
        "COMMIT;"
    )
    try:
        await db.conn.executescript(script)
    except Exception as exc:
        # executescript leaves the transaction open on failure.
        with contextlib.suppress(Exception):  # nothing to roll back if it already ended
            await db.conn.execute("ROLLBACK")
        raise MigrationError(f"Migration {mig.version:04d}_{mig.name} failed: {exc}") from exc
    finally:
        if fk_off:
            await db.conn.execute("PRAGMA foreign_keys = ON")
