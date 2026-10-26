"""Online backup using SQLite's backup API (safe while the bot is running)."""

from __future__ import annotations

import contextlib
import os
import sqlite3
from pathlib import Path


class BackupError(Exception):
    """Backup or integrity check failed."""


def online_backup(src: Path, dest: Path) -> None:
    """Copy `src` to `dest` using the backup API. Result file is mode 600 where supported."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    source = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(tmp)
        try:
            source.backup(target)
        finally:
            target.close()
    except sqlite3.Error as exc:
        tmp.unlink(missing_ok=True)
        raise BackupError(f"Backup failed: {exc}") from exc
    finally:
        source.close()
    with contextlib.suppress(OSError):  # Windows: best effort
        os.chmod(tmp, 0o600)
    os.replace(tmp, dest)


def integrity_check(path: Path) -> bool:
    """True when `PRAGMA integrity_check` reports ok."""
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    return len(rows) == 1 and rows[0][0] == "ok"
