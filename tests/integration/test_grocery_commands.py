"""Run each /grocery command handler end to end with stub interactions (user stories US-G1..G5)."""

from types import SimpleNamespace

import pytest
from discord import app_commands

from carl.discord_ui.auth import resolve_actor
from carl.discord_ui.cogs.grocery import build_grocery_group
from carl.discord_ui.components.confirm import ConfirmButton
from carl.discord_ui.responses import NO_MENTIONS
from carl.domain.errors import Conflict, NotFound, ValidationError
from tests.stubs import make_interaction


@pytest.fixture
def run(ctx):
    """run('add', item='milk') -> the stub interaction after the handler ran."""
    group = build_grocery_group(SimpleNamespace(ctx=ctx))
    commands = {c.name: c for c in group.commands}

    async def go(name, **options):
        inter = make_interaction(ctx)
        inter.extras["actor"] = resolve_actor(inter.guild_id, inter.user, ctx.settings)
        await commands[name].callback(inter, **options)
        return inter

    return go


def choice(value):
    return app_commands.Choice(name=value, value=value)


def last_text(inter):
    return (inter.response.sent or inter.followup.sent)[0][0]


async def test_us_g1_add_a_single_item(run):
    inter = await run("add", item="milk")
    assert last_text(inter) == "Added **milk** (Dairy)."
    assert inter.response.sent[0][1]["ephemeral"] is True
    assert inter.response.sent[0][1]["allowed_mentions"] is NO_MENTIONS


async def test_add_with_every_option(run, ctx):
    inter = await run(
        "add",
        item="oat milk",
        quantity=2.0,
        unit="cartons",
        category=choice("pantry"),
        note="unsweetened",
    )
    assert last_text(inter) == "Added **oat milk** — 2 cartons (Pantry)."
    (item,) = (await ctx.grocery_service.list_items(_actor(ctx))).items
    assert item.note == "unsweetened" and item.category == "pantry"


def _actor(ctx):
    inter = make_interaction(ctx)
    return resolve_actor(inter.guild_id, inter.user, ctx.settings)


async def test_us_g2_duplicates_merge(run):
    await run("add", item="apples", quantity=2.0, unit="lb")
    inter = await run("add", item="Apples", quantity=1.0, unit="lbs")
    assert last_text(inter) == "Merged with existing **apples**: now 3 lb."


async def test_addmany_reports_each_outcome(run):
    inter = await run("addmany", items="eggs, 2 lb apples, paper towels")
    assert last_text(inter) == (
        "Added 3: eggs (Dairy), apples 2 lb (Produce), paper towels (Household)."
    )


async def test_list_is_private_by_default_and_public_on_request(run):
    await run("addmany", items="milk, eggs")
    private = await run("list")
    (_, kwargs) = private.response.sent[0]
    assert kwargs["ephemeral"] is True and "2 needed" in kwargs["embed"].title
    assert kwargs["view"].is_finished()

    shared = await run("list", share=True)
    assert shared.response.sent[0][1]["ephemeral"] is False


async def test_list_filters(run):
    await run("addmany", items="milk, apples")
    only_dairy = await run("list", category=choice("dairy"))
    embed = only_dairy.response.sent[0][1]["embed"]
    assert "Dairy" in embed.title and "milk" in embed.description
    assert "apples" not in embed.description
    purchased = await run("list", view=choice("purchased"))
    assert "Nothing has been checked off" in purchased.response.sent[0][1]["embed"].description


async def test_check_by_id_by_name_and_with_errors(run, ctx):
    await run("addmany", items="milk, eggs, bread")
    items = (await ctx.grocery_service.list_items(_actor(ctx))).items
    by_id = await run("check", item=str(items[0].id))
    assert last_text(by_id).startswith("Checked off **")
    typed = await run("check", item="bread")  # typed without picking a suggestion
    assert last_text(typed) == "Checked off **bread**."
    with pytest.raises(Conflict, match="already checked off"):
        await run("check", item=str(items[0].id))
    with pytest.raises(NotFound, match="couldn't find"):
        await run("check", item="unicorn")


async def test_us_g4_uncheck_returns_the_item(run):
    await run("add", item="apples", quantity=3.0, unit="lb")
    await run("check", item="apples")
    inter = await run("uncheck", item="apples")
    assert last_text(inter) == "Put **apples** — 3 lb back on the list."
    with pytest.raises(Conflict, match="already on the list"):
        await run("uncheck", item="apples")


async def test_edit_and_clear_options(run):
    await run("add", item="apples", quantity=2.0, unit="lb", note="gala")
    inter = await run("edit", item="apples", quantity=5.0, category=choice("snacks"))
    assert last_text(inter) == "Updated **apples** — 5 lb (Snacks; note: gala)."
    cleared = await run("edit", item="apples", clear=choice("note"))
    assert "note:" not in last_text(cleared)
    with pytest.raises(ValidationError, match="Nothing to change"):
        await run("edit", item="apples")


async def test_remove(run):
    await run("add", item="milk")
    inter = await run("remove", item="milk")
    assert last_text(inter) == "Removed **milk**."
    with pytest.raises(NotFound):
        await run("remove", item="milk")


async def test_us_g5_clear_command_asks_first(run, ctx):
    await run("addmany", items="milk, eggs, bread")
    await run("check", item="milk")
    await run("check", item="eggs")
    inter = await run("clear")
    text, kwargs = inter.response.sent[0]
    assert text == "Remove **2** purchased items? This can't be undone."
    yes = kwargs["view"].children[0]
    assert yes.item.label == "Clear 2 items"
    assert ConfirmButton.__discord_ui_compiled_template__.fullmatch(yes.custom_id)
    assert (await ctx.grocery_service.list_items(_actor(ctx), "purchased")).total == 2
