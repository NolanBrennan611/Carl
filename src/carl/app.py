"""AppContext: builds the database, repositories, and services in one place.

Used by the bot and the CLI. No Discord imports here.
"""

from __future__ import annotations

from dataclasses import dataclass

from carl.clock import Clock
from carl.config import Settings
from carl.db.connection import Database, open_db
from carl.db.migrate import migrate
from carl.repositories.app_state_repo import AppStateRepo
from carl.repositories.audit_repo import AuditRepo
from carl.repositories.grocery_repo import GroceryRepo
from carl.repositories.settings_repo import SettingsRepo
from carl.services.grocery_service import GroceryService
from carl.services.settings_service import SettingsService


class DatabaseIntegrityError(Exception):
    """PRAGMA quick_check failed; starting could make things worse."""


@dataclass
class AppContext:
    settings: Settings
    clock: Clock
    db: Database
    app_state: AppStateRepo
    audit: AuditRepo
    settings_service: SettingsService
    grocery_service: GroceryService

    async def close(self) -> None:
        await self.db.close()


def build_context(settings: Settings, clock: Clock, db: Database) -> AppContext:
    app_state = AppStateRepo(db)
    audit = AuditRepo(db)
    settings_repo = SettingsRepo(db)
    return AppContext(
        settings=settings,
        clock=clock,
        db=db,
        app_state=app_state,
        audit=audit,
        settings_service=SettingsService(db, clock, settings_repo, audit),
        grocery_service=GroceryService(db, clock, GroceryRepo(db), audit),
    )


async def start_context(settings: Settings, clock: Clock) -> AppContext:
    """Open the DB, apply migrations (with a pre-migration backup), seed guild settings."""
    db = await open_db(settings.db_path)
    try:
        cur = await db.conn.execute("PRAGMA quick_check")
        row = await cur.fetchone()
        if row is None or row[0] != "ok":
            raise DatabaseIntegrityError(
                "Database integrity check failed. See docs/security-and-operations.md section 8."
            )
        await migrate(
            db,
            clock,
            db_path=settings.db_path,
            backup_dir=settings.data_dir / "backups",
        )
        ctx = build_context(settings, clock, db)
        await ctx.settings_service.seed(settings)
        return ctx
    except BaseException:
        await db.close()
        raise
