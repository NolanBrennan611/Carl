import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from carl.db import migrate as mig
from carl.db.backup import integrity_check, online_backup
from carl.db.connection import open_db

SNAPSHOT = Path(__file__).parents[1] / "fixtures" / "schema_snapshot.sql"
NOW = "2026-10-25T12:00:00.000Z"


async def dump_schema(db) -> str:
    cur = await db.conn.execute(
        "SELECT type, name, sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type, name"
    )
    return "\n\n".join(f"-- {r['type']} {r['name']}\n{r['sql']};" for r in await cur.fetchall())


async def test_schema_matches_committed_snapshot(db):
    assert await dump_schema(db) == SNAPSHOT.read_text(encoding="utf-8").rstrip("\n")


async def test_migrate_is_idempotent(db, clock):
    assert await mig.migrate(db, clock) == []
    st = await mig.status(db)
    assert st.applied == [1]
    assert st.pending == []


async def test_applied_migration_is_recorded_with_checksum(db):
    cur = await db.conn.execute("SELECT version, name, checksum FROM schema_migrations")
    row = await cur.fetchone()
    raw = (mig.MIGRATIONS_DIR / "0001_initial.sql").read_bytes()
    assert (row["version"], row["name"]) == (1, "initial")
    assert row["checksum"] == hashlib.sha256(raw).hexdigest()


async def test_wal_and_foreign_keys_are_on(db):
    for pragma, expected in [("journal_mode", "wal"), ("foreign_keys", 1), ("synchronous", 2)]:
        cur = await db.conn.execute(f"PRAGMA {pragma}")
        assert (await cur.fetchone())[0] == expected


def _copy_migrations(tmp_path) -> Path:
    target = tmp_path / "migs"
    shutil.copytree(mig.MIGRATIONS_DIR, target)
    return target


async def test_tampered_migration_refuses_to_run(tmp_path, clock):
    directory = _copy_migrations(tmp_path)
    db = await open_db(tmp_path / "t.db")
    try:
        await mig.migrate(db, clock, directory=directory)
        path = directory / "0001_initial.sql"
        path.write_text(path.read_text() + "\n-- sneaky edit\n")
        with pytest.raises(mig.MigrationError, match="modified after being applied"):
            await mig.migrate(db, clock, directory=directory)
    finally:
        await db.close()


async def test_database_newer_than_code_is_refused(tmp_path, clock):
    directory = _copy_migrations(tmp_path)
    (directory / "0002_extra.sql").write_text("CREATE TABLE extra (id INTEGER PRIMARY KEY) STRICT;")
    db = await open_db(tmp_path / "t.db")
    try:
        await mig.migrate(db, clock, directory=directory)
        (directory / "0002_extra.sql").unlink()
        with pytest.raises(mig.MigrationError, match="doesn't know"):
            await mig.migrate(db, clock, directory=directory)
    finally:
        await db.close()


async def test_failed_migration_rolls_back_and_is_not_recorded(tmp_path, clock):
    directory = _copy_migrations(tmp_path)
    (directory / "0002_bad.sql").write_text(
        "CREATE TABLE half_done (id INTEGER PRIMARY KEY) STRICT;\nTHIS IS NOT SQL;"
    )
    db = await open_db(tmp_path / "t.db")
    try:
        with pytest.raises(mig.MigrationError, match="0002_bad failed"):
            await mig.migrate(db, clock, directory=directory)
        st = await mig.status(db, directory)
        assert st.applied == [1] and st.pending == [2]
        cur = await db.conn.execute("SELECT name FROM sqlite_schema WHERE name = 'half_done'")
        assert await cur.fetchone() is None
        # the connection is usable afterwards
        await db.conn.execute("SELECT 1")
    finally:
        await db.close()


async def test_pre_migration_backup_created_when_upgrading_existing_db(tmp_path, clock):
    directory = _copy_migrations(tmp_path)
    db_path = tmp_path / "t.db"
    backup_dir = tmp_path / "backups"
    db = await open_db(db_path)
    try:
        # first install: nothing to back up
        await mig.migrate(db, clock, db_path=db_path, backup_dir=backup_dir, directory=directory)
        assert not backup_dir.exists()
        (directory / "0002_extra.sql").write_text(
            "CREATE TABLE extra (id INTEGER PRIMARY KEY) STRICT;"
        )
        assert await mig.migrate(
            db, clock, db_path=db_path, backup_dir=backup_dir, directory=directory
        ) == [2]
    finally:
        await db.close()
    backups = list(backup_dir.glob("pre-migration-0002-*.db"))
    assert len(backups) == 1
    assert integrity_check(backups[0])
    conn = sqlite3.connect(backups[0])
    try:  # the backup holds the pre-upgrade schema
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_schema")}
    finally:
        conn.close()
    assert "extra" not in names and "bills" in names


def test_migration_files_must_be_contiguous(tmp_path):
    (tmp_path / "0001_a.sql").write_text("SELECT 1;")
    (tmp_path / "0003_c.sql").write_text("SELECT 1;")
    with pytest.raises(mig.MigrationError, match="contiguous"):
        mig.discover(tmp_path)


def test_bad_migration_file_name(tmp_path):
    (tmp_path / "init.sql").write_text("SELECT 1;")
    with pytest.raises(mig.MigrationError, match="Bad migration file name"):
        mig.discover(tmp_path)


async def test_online_backup_round_trip(db, tmp_path):
    await db.conn.execute(
        "INSERT INTO app_state (key, value, updated_at) VALUES ('k', 'v', ?)", (NOW,)
    )
    dest = tmp_path / "out" / "copy.db"
    online_backup(tmp_path / "test.db", dest)
    assert integrity_check(dest)
    conn = sqlite3.connect(dest)
    try:
        assert conn.execute("SELECT value FROM app_state WHERE key = 'k'").fetchone()[0] == "v"
    finally:
        conn.close()


def test_integrity_check_flags_garbage(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a database" * 100)
    assert integrity_check(bad) is False


# ---- constraints (docs/database-design.md section 4) -------------------------------------------
async def _insert_grocery(db, **kw):
    row = {
        "guild_id": 1, "name": "apples", "name_normalized": "apple", "unit_normalized": "",
        "category": "produce", "status": "needed", "added_by_user_id": 5,
        "purchased_at": None, "quantity": None,
    }  # fmt: skip
    row.update(kw)
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    await db.conn.execute(
        f"INSERT INTO grocery_items ({cols}, created_at, updated_at) VALUES ({marks}, ?, ?)",
        (*row.values(), NOW, NOW),
    )


async def test_check_constraints_reject_bad_enums_and_lengths(db):
    for bad in [
        {"category": "snacks!"},
        {"status": "lost"},
        {"quantity": 0},
        {"quantity": 10000},
        {"name": ""},
        {"name": "x" * 101},
    ]:
        with pytest.raises(sqlite3.IntegrityError):
            await _insert_grocery(db, **bad)


async def test_purchased_status_requires_timestamp(db):
    with pytest.raises(sqlite3.IntegrityError):
        await _insert_grocery(db, status="purchased", purchased_at=None)
    with pytest.raises(sqlite3.IntegrityError):
        await _insert_grocery(db, status="needed", purchased_at=NOW)
    await _insert_grocery(db, status="purchased", purchased_at=NOW)


async def test_only_one_needed_row_per_name_and_unit(db):
    await _insert_grocery(db)
    with pytest.raises(sqlite3.IntegrityError):
        await _insert_grocery(db)  # duplicate needed item
    await _insert_grocery(db, unit_normalized="lb")  # different unit is fine
    await _insert_grocery(db, guild_id=2)  # different guild is fine
    await _insert_grocery(db, status="purchased", purchased_at=NOW)  # purchased rows may repeat
    await _insert_grocery(db, status="purchased", purchased_at=NOW)


async def _insert_bill(db, **kw):
    row = {
        "guild_id": 1, "scope": "household", "owner_user_id": 5, "name": "Electric",
        "name_normalized": "electric", "currency": "USD", "first_due_date": "2026-11-01",
        "archived_at": None,
    }  # fmt: skip
    row.update(kw)
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    await db.conn.execute(
        f"INSERT INTO bills ({cols}, created_at, updated_at) VALUES ({marks}, ?, ?)",
        (*row.values(), NOW, NOW),
    )


async def test_active_bill_names_unique_per_scope_and_owner(db):
    await _insert_bill(db)
    with pytest.raises(sqlite3.IntegrityError):
        await _insert_bill(db, owner_user_id=6)  # household bills ignore the owner
    await _insert_bill(db, scope="personal", owner_user_id=5)
    await _insert_bill(db, scope="personal", owner_user_id=6)  # others may reuse a name
    with pytest.raises(sqlite3.IntegrityError):
        await _insert_bill(db, scope="personal", owner_user_id=5)
    await _insert_bill(db, name="Old", name_normalized="electric", archived_at=NOW)  # archived ok


async def test_task_constraints(db):
    base = (
        "INSERT INTO tasks (guild_id, scope, owner_user_id, assignee_user_id, title, due_date,"
        " recurrence_json, created_at, updated_at) VALUES (1, ?, 5, ?, 't', ?, ?, ?, ?)"
    )
    with pytest.raises(sqlite3.IntegrityError):  # personal tasks can't have assignees
        await db.conn.execute(base, ("personal", 6, None, None, NOW, NOW))
    with pytest.raises(sqlite3.IntegrityError):  # recurring needs a due date
        await db.conn.execute(base, ("household", None, None, '{"v":1}', NOW, NOW))
    await db.conn.execute(base, ("household", 6, "2026-11-02", '{"v":1}', NOW, NOW))


async def test_notification_dedupe_key_is_unique_and_dm_needs_user(db):
    sql = (
        "INSERT INTO notifications (guild_id, kind, dedupe_key, target_type, target_user_id,"
        " scheduled_for, expires_at, next_attempt_at, created_at, updated_at)"
        " VALUES (1, 'bill_reminder', ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    args = ("household_channel", None, NOW, NOW, NOW, NOW, NOW)
    await db.conn.execute(sql, ("br:1:2026-11-01:3", *args))
    with pytest.raises(sqlite3.IntegrityError):
        await db.conn.execute(sql, ("br:1:2026-11-01:3", *args))
    with pytest.raises(sqlite3.IntegrityError):
        await db.conn.execute(sql, ("br:1:2026-11-01:0", "user_dm", None, NOW, NOW, NOW, NOW, NOW))


async def test_sent_notification_requires_message_id(db):
    with pytest.raises(sqlite3.IntegrityError):
        await db.conn.execute(
            "INSERT INTO notifications (guild_id, kind, dedupe_key, target_type, scheduled_for,"
            " expires_at, status, next_attempt_at, created_at, updated_at)"
            " VALUES (1, 'bill_reminder', 'k', 'household_channel', ?, ?, 'sent', ?, ?, ?)",
            (NOW, NOW, NOW, NOW, NOW),
        )


async def test_occurrence_unique_per_bill_and_date_and_cascade(db):
    await _insert_bill(db)
    occ = (
        "INSERT INTO bill_occurrences (bill_id, guild_id, due_date, created_at, updated_at)"
        " VALUES (1, 1, ?, ?, ?)"
    )
    await db.conn.execute(occ, ("2026-11-01", NOW, NOW))
    with pytest.raises(sqlite3.IntegrityError):
        await db.conn.execute(occ, ("2026-11-01", NOW, NOW))
    await db.conn.execute("DELETE FROM bills WHERE id = 1")
    cur = await db.conn.execute("SELECT count(*) FROM bill_occurrences")
    assert (await cur.fetchone())[0] == 0


async def test_foreign_key_violation_rejected(db):
    with pytest.raises(sqlite3.IntegrityError):
        await db.conn.execute(
            "INSERT INTO bill_occurrences (bill_id, guild_id, due_date, created_at, updated_at)"
            " VALUES (999, 1, '2026-11-01', ?, ?)",
            (NOW, NOW),
        )


async def test_transaction_rolls_back_on_error(db):
    with pytest.raises(RuntimeError):
        async with db.transaction():
            await db.conn.execute(
                "INSERT INTO app_state (key, value, updated_at) VALUES ('a', 'b', ?)", (NOW,)
            )
            raise RuntimeError("boom")
    cur = await db.conn.execute("SELECT count(*) FROM app_state")
    assert (await cur.fetchone())[0] == 0
    async with db.transaction():  # still usable
        await db.conn.execute(
            "INSERT INTO app_state (key, value, updated_at) VALUES ('a', 'b', ?)", (NOW,)
        )
    cur = await db.conn.execute("SELECT count(*) FROM app_state")
    assert (await cur.fetchone())[0] == 1
