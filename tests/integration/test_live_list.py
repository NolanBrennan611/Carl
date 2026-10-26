"""The live grocery list message, and short-lived (self-deleting) replies."""

import json
import logging
from types import SimpleNamespace

import discord
import pytest
from discord import app_commands

from carl.discord_ui import responses
from carl.discord_ui.auth import resolve_actor
from carl.discord_ui.bot import CarlBot
from carl.discord_ui.cogs.grocery import build_grocery_group
from carl.discord_ui.components.confirm import ConfirmButton
from carl.discord_ui.components.grocery import GroceryItemSelect, ask_clear, build_list_view
from carl.discord_ui.live_list import STATE_KEY, LiveList
from carl.domain.models import Actor
from tests.conftest import GUILD_ID
from tests.stubs import http_error, make_interaction

ALEX = Actor(GUILD_ID, 7)


@pytest.fixture
def run(ctx, discord_fake):
    bot = SimpleNamespace(ctx=ctx, live_list=discord_fake.live_list(ctx))
    commands = {c.name: c for c in build_grocery_group(bot).commands}

    async def go(name, **options):
        inter = make_interaction(ctx, discord_fake=discord_fake)
        inter.extras["actor"] = resolve_actor(inter.guild_id, inter.user, ctx.settings)
        await commands[name].callback(inter, **options)
        return inter

    return go


@pytest.fixture
async def live(ctx, discord_fake, run):
    """A shared list is posted (so it is live) and its first rendering is discarded."""
    await run("addmany", items="milk, eggs")
    await run("list")
    discord_fake.edits.clear()
    return discord_fake


def stored(ctx):
    async def read():
        raw = await ctx.app_state.get(STATE_KEY)
        return json.loads(raw) if raw else None

    return read()


def live_text(fake):
    """Everything shown in the most recent edit of the live message."""
    embed = fake.edits[-1]["embed"]
    return embed.title + "\n" + (embed.description or "")


def choice(value):
    return app_commands.Choice(name=value, value=value)


# ---- remembering the live message
def test_share_defaults_to_true():
    command = next(c for c in build_grocery_group(SimpleNamespace()).commands if c.name == "list")
    share = next(p for p in command.parameters if p.name == "share")
    assert share.default is True and not share.required


async def test_a_public_list_becomes_the_live_list(run, ctx):
    posted = await run("list")
    ref = await stored(ctx)
    assert ref == {"channel_id": 555, "message_id": 9001, "view": "needed", "category": None}
    assert posted.response.sent[0][1]["ephemeral"] is False


async def test_a_private_list_is_not_remembered(run, ctx):
    await run("list", share=False)
    assert await stored(ctx) is None


async def test_the_view_and_category_are_remembered_too(run, ctx, discord_fake):
    await run("addmany", items="milk, apples")
    await run("list", category=choice("dairy"))
    assert (await stored(ctx))["category"] == "dairy"
    await run("add", item="cheese")
    text = live_text(discord_fake)
    assert "Dairy" in text and "cheese" in text and "apples" not in text


# ---- every kind of change updates it
async def test_add_updates_the_live_list(run, live):
    await run("add", item="bread")
    assert "bread" in live_text(live)
    (edit,) = live.edits
    assert (edit["channel_id"], edit["message_id"]) == (555, 9001)
    assert edit["view"].is_finished() and edit["embed"].title.endswith("3 needed")


async def test_merging_updates_the_live_list(run, live):
    await run("add", item="apples", quantity=2.0, unit="lb")
    await run("add", item="apples", quantity=1.0, unit="lb")
    assert "apples — 3 lb" in live_text(live)


async def test_addmany_updates_the_live_list(run, live):
    await run("addmany", items="bread, butter")
    assert "bread" in live_text(live) and "butter" in live_text(live)


async def test_check_and_uncheck_update_the_live_list(run, live):
    await run("check", item="milk")
    assert "milk" not in live_text(live) and "1 needed" in live_text(live)
    await run("uncheck", item="milk")
    assert "milk" in live_text(live) and "2 needed" in live_text(live)


async def test_edit_and_remove_update_the_live_list(run, live):
    await run("edit", item="milk", quantity=3.0, unit="gal")
    assert "milk — 3 gal" in live_text(live)
    await run("remove", item="milk")
    assert "milk" not in live_text(live)


async def test_the_tick_off_menu_on_another_message_updates_the_live_list(ctx, live, discord_fake):
    svc = ctx.grocery_service
    page = await svc.list_items(ALEX)
    select = build_list_view(page).children[0]
    inter = make_interaction(ctx, discord_fake=discord_fake, message_id=1234)  # not the live one
    match = GroceryItemSelect.__discord_ui_compiled_template__.fullmatch(select.custom_id)
    item = await GroceryItemSelect.from_custom_id(inter, None, match)
    item._refresh_state(inter, {"values": [str(page.items[0].id)]})
    await item.callback(inter)
    assert len(discord_fake.edits) == 1 and "1 needed" in live_text(discord_fake)


async def test_clicking_the_live_message_itself_is_not_edited_twice(ctx, live, discord_fake):
    page = await ctx.grocery_service.list_items(ALEX)
    select = build_list_view(page).children[0]
    inter = make_interaction(ctx, discord_fake=discord_fake, message_id=9001)  # the live one
    match = GroceryItemSelect.__discord_ui_compiled_template__.fullmatch(select.custom_id)
    item = await GroceryItemSelect.from_custom_id(inter, None, match)
    item._refresh_state(inter, {"values": [str(page.items[0].id)]})
    await item.callback(inter)
    assert len(inter.response.edits) == 1  # the click's own edit shows the new state
    assert discord_fake.edits == []  # no second edit through the API


async def test_confirming_clear_updates_the_live_list(ctx, live, discord_fake, run):
    await run("check", item="milk")
    discord_fake.edits.clear()
    inter = make_interaction(ctx, discord_fake=discord_fake)
    await ask_clear(inter, ALEX)
    view = inter.response.sent[0][1]["view"]
    yes = view.children[0]
    click = make_interaction(ctx, discord_fake=discord_fake, message_id=4321)
    match = ConfirmButton.__discord_ui_compiled_template__.fullmatch(yes.custom_id)
    await (await ConfirmButton.from_custom_id(click, yes.item, match)).callback(click)
    assert click.response.edits[0]["embed"].description == "Cleared 1 purchased item."
    assert len(discord_fake.edits) == 1 and "1 needed" in live_text(discord_fake)


async def test_a_change_that_changes_nothing_does_not_touch_the_live_list(run, live):
    await run("add", item="milk")  # already on the list, nothing new
    await run("addmany", items="0 gum")  # rejected
    assert live.edits == []


async def test_changes_work_when_there_is_no_live_list(run, discord_fake):
    await run("add", item="milk")
    await run("check", item="milk")
    assert discord_fake.edits == []


# ---- replacing
async def test_posting_a_new_list_deletes_the_old_one(run, ctx, discord_fake):
    await run("list")
    await run("list")
    assert discord_fake.deletes == [(555, 9001)]
    assert (await stored(ctx))["message_id"] == 9002
    await run("add", item="bread")
    assert discord_fake.edits[-1]["message_id"] == 9002  # only the newest is kept up to date


async def test_a_private_list_does_not_replace_the_live_one(run, ctx, discord_fake):
    await run("list")
    await run("list", share=False)
    assert discord_fake.deletes == []
    assert (await stored(ctx))["message_id"] == 9001


async def test_replacing_works_even_if_the_old_message_is_already_gone(run, ctx, discord_fake):
    await run("list")
    discord_fake.delete_error = http_error(discord.NotFound, 404)
    await run("list")
    assert (await stored(ctx))["message_id"] == 9002


# ---- never failing the user
@pytest.mark.parametrize("error_type", [discord.NotFound, discord.Forbidden])
async def test_a_missing_or_uneditable_message_is_forgotten_quietly(
    run, ctx, live, caplog, error_type
):
    live.edit_error = http_error(error_type, 404 if error_type is discord.NotFound else 403)
    with caplog.at_level(logging.WARNING, logger="carl.live_list"):
        inter = await run("add", item="bread")  # the command itself still succeeds
    assert inter.response.sent[0][1]["embed"].description.startswith("Added")
    assert await stored(ctx) in (None, "")  # forgotten
    assert "live_list_lost" in caplog.text
    live.edit_error = None
    await run("add", item="butter")  # later changes don't keep retrying
    assert live.edits == []


async def test_a_temporary_discord_error_keeps_the_live_list(run, ctx, live, caplog):
    live.edit_error = http_error(discord.HTTPException, 503)
    with caplog.at_level(logging.WARNING, logger="carl.live_list"):
        await run("add", item="bread")
    assert "live_list_edit_failed" in caplog.text
    assert (await stored(ctx))["message_id"] == 9001  # still remembered
    live.edit_error = None
    await run("add", item="butter")
    assert "butter" in live_text(live) and "bread" in live_text(live)  # caught up


async def test_unreadable_saved_state_is_discarded(ctx, run, discord_fake, caplog):
    now = "2026-10-25T12:00:00.000Z"
    async with ctx.db.transaction():
        await ctx.app_state.set(STATE_KEY, "not json", now)
    with caplog.at_level(logging.WARNING, logger="carl.live_list"):
        inter = await run("add", item="bread")
    assert inter.response.sent  # the command worked
    assert discord_fake.edits == []
    assert await stored(ctx) in (None, "")


async def test_a_rendering_failure_never_reaches_the_user(ctx, live, monkeypatch, caplog):
    async def boom(*_a, **_k):
        raise RuntimeError("render exploded")

    monkeypatch.setattr("carl.discord_ui.live_list.render_list", boom)
    inter = make_interaction(ctx, discord_fake=live)
    with caplog.at_level(logging.ERROR, logger="carl.live_list"):
        await live.live_list(ctx).refresh_after(inter)  # must not raise
    assert "live_list_refresh_failed" in caplog.text


async def test_rapid_changes_leave_the_newest_state_on_screen(run, live):
    import asyncio

    await asyncio.gather(*(run("add", item=f"snack {n}") for n in range(6)))
    assert all(f"snack {n}" in live_text(live) for n in range(6))
    assert live.edits[-1]["embed"].title.endswith("8 needed")


async def test_the_bot_owns_a_live_list(ctx):
    bot = CarlBot(ctx)
    try:
        assert isinstance(bot.live_list, LiveList)
    finally:
        await bot.close()


# ---- short-lived replies
async def test_success_replies_are_small_private_embeds_that_delete_themselves(run):
    inter = await run("add", item="milk", quantity=2.0, unit="cartons")
    (content, kwargs) = inter.response.sent[0]
    assert content is None
    assert kwargs["embed"].description == "Added **milk** — 2 cartons (Dairy)."
    assert kwargs["ephemeral"] is True
    assert kwargs["delete_after"] == responses.BRIEF_SECONDS
    assert kwargs["allowed_mentions"] is responses.NO_MENTIONS


@pytest.mark.parametrize(
    ("command", "options"),
    [
        ("addmany", {"items": "bread, butter"}),
        ("check", {"item": "milk"}),
        ("uncheck", {"item": "milk"}),
        ("edit", {"item": "eggs", "note": "large"}),
        ("remove", {"item": "eggs"}),
    ],
)
async def test_every_success_reply_deletes_itself(run, command, options):
    await run("addmany", items="milk, eggs")
    if command == "uncheck":
        await run("check", item="milk")
    inter = await run(command, **options)
    assert inter.response.sent[0][1]["delete_after"] == responses.BRIEF_SECONDS


async def test_the_delay_is_one_constant_well_under_the_interaction_limit():
    assert 0 < responses.BRIEF_SECONDS <= 30
    assert responses.BRIEF_SECONDS < 15 * 60  # Discord's interaction token lifetime


async def test_partial_failures_stay_on_screen(run):
    inter = await run("addmany", items="bread, 0 gum")
    (content, kwargs) = inter.response.sent[0]
    assert "Couldn't add 1" in content  # plain message, readable as long as needed
    assert "delete_after" not in kwargs and "embed" not in kwargs


async def test_error_replies_are_never_auto_deleted(ctx):
    bot = CarlBot(ctx)
    try:
        inter = make_interaction(ctx)
        cmd = SimpleNamespace(name="stub")
        from carl.domain.errors import NotFound

        await bot.tree.on_error(inter, app_commands.CommandInvokeError(cmd, NotFound("Nope.")))
        (content, kwargs) = inter.response.sent[0]
        assert content == "Nope." and "delete_after" not in kwargs
    finally:
        await bot.close()


async def test_a_brief_reply_after_the_interaction_was_answered_schedules_its_deletion(ctx):
    inter = make_interaction(ctx)
    inter.response.done = True
    await responses.respond_brief(inter, "Done.", delay=7)
    ((_, kwargs),) = inter.followup.sent
    assert kwargs["ephemeral"] is True and kwargs["wait"] is True
    assert inter.followup.scheduled_deletes == [7]


async def test_list_messages_are_not_auto_deleted(run):
    inter = await run("list")
    assert "delete_after" not in inter.response.sent[0][1]


async def test_summary_embeds_are_clipped(ctx):
    embed = responses.summary_embed("x" * 9000)
    assert len(embed.description) <= responses.MAX_EMBED_TEXT


async def test_checking_off_via_uncheck_mode_menu_also_refreshes(ctx, live, discord_fake):
    svc = ctx.grocery_service
    first = (await svc.list_items(ALEX)).items[0]
    await svc.check_one(ALEX, first.id)
    page = await svc.list_items(ALEX, "purchased")
    select = build_list_view(page).children[0]
    inter = make_interaction(ctx, discord_fake=discord_fake, message_id=777)
    match = GroceryItemSelect.__discord_ui_compiled_template__.fullmatch(select.custom_id)
    item = await GroceryItemSelect.from_custom_id(inter, None, match)
    item._refresh_state(inter, {"values": [str(first.id)]})
    await item.callback(inter)
    assert "2 needed" in live_text(discord_fake)
