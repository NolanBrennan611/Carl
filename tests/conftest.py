from __future__ import annotations

from pathlib import Path

import pytest

from carl.app import AppContext, build_context
from carl.config import Settings, load_settings
from carl.db.connection import Database, open_db
from carl.db.migrate import migrate
from tests.fakes import FakeClock

GUILD_ID = 1000
ROLE_ID = 2000
ADMIN_ROLE_ID = 3000
TOKEN = (
    "MTIzNDU2Nzg5MDEyMzQ1Njc4" + "." + "GabcDE" + "." + "abcdefghijklmnopqrstuvwxyz0"
)  # fake, split on purpose


def make_env(data_dir: Path, **overrides: str) -> dict[str, str]:
    env = {
        "DISCORD_TOKEN": TOKEN,
        "CARL_GUILD_ID": str(GUILD_ID),
        "CARL_HOUSEHOLD_ROLE_ID": str(ROLE_ID),
        "CARL_ADMIN_ROLE_ID": str(ADMIN_ROLE_ID),
        "CARL_DEFAULT_TIMEZONE": "America/Chicago",
        "CARL_DATA_DIR": str(data_dir),
    }
    env.update(overrides)
    return env


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(make_env(tmp_path / "data"))


@pytest.fixture
async def db(tmp_path: Path, clock: FakeClock) -> Database:
    database = await open_db(tmp_path / "test.db")
    await migrate(database, clock)
    yield database
    await database.close()


@pytest.fixture
async def ctx(db: Database, settings: Settings, clock: FakeClock) -> AppContext:
    context = build_context(settings, clock, db)
    await context.settings_service.seed(settings)
    return context


@pytest.fixture
def discord_fake():
    from tests.stubs import FakeDiscord

    return FakeDiscord()
