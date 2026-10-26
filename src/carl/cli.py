"""Command line: run | migrate [--status] | check-config | backup.

Exit codes: 0 ok, 2 bad config, 3 another instance running, 4 migration failure,
5 database integrity failure.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from carl import __version__
from carl.app import DatabaseIntegrityError, start_context
from carl.clock import SystemClock
from carl.config import ConfigError, Settings, load_settings
from carl.db import migrate as migrations
from carl.db.backup import BackupError, online_backup
from carl.db.connection import open_db
from carl.lockfile import InstanceLock, LockHeldError
from carl.logging_setup import setup_logging

EXIT_OK, EXIT_CONFIG, EXIT_LOCK, EXIT_MIGRATION, EXIT_INTEGRITY = 0, 2, 3, 4, 5

log = logging.getLogger("carl.cli")


def _data_dir() -> Path:
    return Path(os.environ.get("CARL_DATA_DIR", "").strip() or "./data")


def _load_settings_or_exit() -> Settings | None:
    try:
        return load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return None


def cmd_check_config(_: argparse.Namespace) -> int:
    settings = _load_settings_or_exit()
    if settings is None:
        return EXIT_CONFIG
    print("Configuration OK")
    print(f"  version:        {__version__}")
    print(f"  environment:    {settings.env}")
    print(f"  token:          {settings.discord_token}")
    print(f"  guild id:       {settings.guild_id}")
    print(f"  household role: {settings.household_role_id}")
    print(f"  admin role:     {settings.admin_role_id or '(none; Manage Server permission)'}")
    print(f"  time zone:      {settings.default_timezone}")
    print(f"  data dir:       {settings.data_dir.resolve()}")
    print(f"  health ping:    {'configured' if settings.healthcheck_url else 'off'}")
    return EXIT_OK


def cmd_migrate(args: argparse.Namespace) -> int:
    data_dir = _data_dir()
    db_path = data_dir / "carl.db"

    async def go() -> int:
        db = await open_db(db_path)
        try:
            if args.status:
                st = await migrations.status(db)
                print(f"applied: {st.applied or 'none'}")
                print(f"pending: {st.pending or 'none'}")
                return EXIT_OK
            done = await migrations.migrate(
                db, SystemClock(), db_path=db_path, backup_dir=data_dir / "backups"
            )
            print(f"applied migrations: {done}" if done else "already up to date")
            return EXIT_OK
        except migrations.MigrationError as exc:
            print(f"Migration error: {exc}", file=sys.stderr)
            return EXIT_MIGRATION
        finally:
            await db.close()

    return asyncio.run(go())


def cmd_backup(_: argparse.Namespace) -> int:
    data_dir = _data_dir()
    db_path = data_dir / "carl.db"
    if not db_path.exists():
        print(f"No database at {db_path}", file=sys.stderr)
        return EXIT_CONFIG
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = data_dir / "backups" / f"manual-{stamp}.db"
    try:
        online_backup(db_path, dest)
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INTEGRITY
    print(f"Backup written: {dest}")
    return EXIT_OK


def cmd_run(_: argparse.Namespace) -> int:
    settings = _load_settings_or_exit()
    if settings is None:
        return EXIT_CONFIG
    setup_logging(settings.log_level)

    lock = InstanceLock(settings.data_dir / "carl.lock")
    try:
        lock.acquire()
    except LockHeldError as exc:
        log.error("lock_held %s", exc)
        return EXIT_LOCK
    try:
        return asyncio.run(_run_bot(settings))
    finally:
        lock.release()


async def _run_bot(settings: Settings) -> int:
    # Imported here so the CLI (check-config, migrate, backup) never loads the Discord layer.
    import discord

    from carl.discord_ui.bot import CarlBot

    clock = SystemClock()
    try:
        ctx = await start_context(settings, clock)
    except migrations.MigrationError as exc:
        log.critical("migration_failed %s", exc)
        return EXIT_MIGRATION
    except DatabaseIntegrityError as exc:
        log.critical("database_integrity_failed %s", exc)
        return EXIT_INTEGRITY

    bot = CarlBot(ctx)
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(bot.close()))
    exit_code = EXIT_OK
    try:
        await bot.start(settings.discord_token.get())
    except discord.LoginFailure:
        log.critical("discord_login_failed the token was rejected; check DISCORD_TOKEN")
        exit_code = EXIT_CONFIG
    except asyncio.CancelledError:
        pass
    finally:
        await bot.close()
        await ctx.close()
        log.info("stopped")
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="carl", description="Household Discord bot")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="start the bot").set_defaults(func=cmd_run)
    sub.add_parser("check-config", help="validate environment").set_defaults(func=cmd_check_config)
    mig = sub.add_parser("migrate", help="apply database migrations")
    mig.add_argument("--status", action="store_true", help="show applied/pending only")
    mig.set_defaults(func=cmd_migrate)
    sub.add_parser("backup", help="write a database backup now").set_defaults(func=cmd_backup)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # reads .env when present; real environment variables win
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_CONFIG
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return EXIT_OK
