import pytest

from carl.domain.errors import Forbidden, NotFound, ValidationError
from carl.domain.models import Actor
from tests.conftest import GUILD_ID

ADMIN = Actor(GUILD_ID, 1, True)
MEMBER = Actor(GUILD_ID, 2, False)


async def test_seed_creates_settings_from_environment(ctx):
    s = await ctx.settings_service.get(GUILD_ID)
    assert s.timezone == "America/Chicago"
    assert s.reminder_time == "09:00"
    assert s.default_currency == "USD"
    assert s.default_bill_offsets == (3, 0)
    assert s.reminder_channel_id is None
    assert s.summary_frequency == "off"
    assert s.date_order == "MDY"


async def test_seed_twice_keeps_admin_changes(ctx, settings):
    await ctx.settings_service.setup(ADMIN, timezone="Europe/Paris")
    again = await ctx.settings_service.seed(settings)
    assert again.timezone == "Europe/Paris"


async def test_setup_updates_only_provided_fields(ctx):
    before = await ctx.settings_service.get(GUILD_ID)
    after = await ctx.settings_service.setup(
        ADMIN,
        reminder_channel_id=555,
        timezone="America/Denver",
        reminder_time="08:30",
        currency="cad",
        default_remind="7,3,0",
        date_order="dmy",
    )
    assert after.reminder_channel_id == 555
    assert after.timezone == "America/Denver"
    assert after.reminder_time == "08:30"
    assert after.default_currency == "CAD"
    assert after.default_bill_offsets == (7, 3, 0)
    assert after.date_order == "DMY"
    assert after.summary_frequency == before.summary_frequency
    assert await ctx.settings_service.get(GUILD_ID) == after


async def test_settings_survive_reopening_the_database(tmp_path, clock, settings):
    from carl.app import start_context

    ctx1 = await start_context(settings, clock)
    await ctx1.settings_service.setup(ADMIN, timezone="Asia/Tokyo", reminder_time="07:15")
    await ctx1.close()
    ctx2 = await start_context(settings, clock)
    try:
        s = await ctx2.settings_service.get(GUILD_ID)
        assert (s.timezone, s.reminder_time) == ("Asia/Tokyo", "07:15")
    finally:
        await ctx2.close()


async def test_non_admin_cannot_change_settings(ctx):
    with pytest.raises(Forbidden):
        await ctx.settings_service.setup(MEMBER, timezone="Asia/Tokyo")
    assert (await ctx.settings_service.get(GUILD_ID)).timezone == "America/Chicago"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timezone": "Mars/Olympus"},
        {"reminder_time": "25:00"},
        {"currency": "dollars"},
        {"default_remind": "99"},
        {"default_remind": "a,b"},
        {"date_order": "YMD"},
        {},
    ],
)
async def test_invalid_input_is_rejected_and_nothing_changes(ctx, kwargs):
    before = await ctx.settings_service.get(GUILD_ID)
    with pytest.raises(ValidationError):
        await ctx.settings_service.setup(ADMIN, **kwargs)
    assert await ctx.settings_service.get(GUILD_ID) == before


async def test_one_invalid_field_prevents_partial_update(ctx):
    before = await ctx.settings_service.get(GUILD_ID)
    with pytest.raises(ValidationError):
        await ctx.settings_service.setup(ADMIN, timezone="Asia/Tokyo", reminder_time="bad")
    assert await ctx.settings_service.get(GUILD_ID) == before


async def test_unknown_guild_is_not_found(ctx):
    with pytest.raises(NotFound):
        await ctx.settings_service.get(GUILD_ID + 1)


async def test_audit_entry_lists_field_names_not_values(ctx):
    await ctx.settings_service.setup(ADMIN, timezone="Asia/Tokyo", currency="JPY")
    cur = await ctx.db.conn.execute("SELECT * FROM audit_log")
    rows = await cur.fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert (row["action"], row["actor_user_id"], row["guild_id"]) == (
        "settings.update",
        1,
        GUILD_ID,
    )
    assert row["details_json"] == '{"fields":["timezone","currency"]}'
    assert "Tokyo" not in row["details_json"]
    assert row["at"] == "2026-10-25T12:00:00.000Z"
