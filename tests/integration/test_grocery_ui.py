"""Grocery Discord layer: text, embeds, persistent components, access checks. All offline."""

import re

import discord
import pytest

from carl.discord_ui import grocery_messages as msg
from carl.discord_ui.auth import NO_ACCESS
from carl.discord_ui.cogs.grocery import build_grocery_group, unit_matches
from carl.discord_ui.components import ids
from carl.discord_ui.components.confirm import (
    EXPIRED,
    NOT_YOURS,
    ConfirmButton,
    build_confirm_view,
    check_confirm,
)
from carl.discord_ui.components.grocery import (
    GroceryClearAsk,
    GroceryItemSelect,
    GroceryNavButton,
    ask_clear,
    build_list_view,
    render_list,
)
from carl.domain.models import Actor
from carl.services.grocery_service import AddItemInput
from tests.conftest import GUILD_ID
from tests.stubs import make_interaction, make_member

ALEX = Actor(GUILD_ID, 7)


@pytest.fixture
def svc(ctx):
    return ctx.grocery_service


# ---- custom ids
def test_ids_round_trip_and_reject_bad_parts():
    custom_id = ids.build("gl", "go", "next", "needed", ids.cat_token(None), 3)
    assert custom_id == "carl:v1:gl:go:next:needed:_:3"
    assert ids.parse(custom_id) == ["gl", "go", "next", "needed", "_", "3"]
    assert ids.parse("someone-else:1") is None
    assert ids.cat_from_token("_") is None and ids.cat_from_token("dairy") == "dairy"
    with pytest.raises(ValueError):
        ids.build("a:b")
    with pytest.raises(ValueError):
        ids.build("x" * 120)


# ---- confirmation rules
def test_check_confirm_rules():
    assert check_confirm(7, 7, 1000, 999.0) is None
    assert check_confirm(7, 7, 1000, 1000.0) is None  # the last second still counts
    assert check_confirm(7, 8, 1000, 999.0) == NOT_YOURS
    assert check_confirm(7, 7, 1000, 1001.0) == EXPIRED
    assert check_confirm(7, 8, 1000, 1001.0) == NOT_YOURS  # wrong user wins over expired


async def test_confirm_buttons_encode_everything_and_round_trip():
    view = build_confirm_view("gclear", 7, 123456789012345678, 1_800_000_000, yes_label="Clear 7")
    yes, no = view.children
    assert view.is_finished()  # not kept in memory; the persistent item handles clicks
    for button, answer in ((yes, "yes"), (no, "no")):
        assert len(button.custom_id) <= 100
        match = ConfirmButton.__discord_ui_compiled_template__.fullmatch(button.custom_id)
        assert match and match["ans"] == answer and match["action"] == "gclear"
        assert int(match["exp"]) == 1_800_000_120 and int(match["target"]) == 7
        again = await ConfirmButton.from_custom_id(None, button.item, match)
        assert again.custom_id == button.custom_id
    assert yes.item.style == discord.ButtonStyle.danger


# ---- reply text
async def test_add_replies(svc):
    out = await svc.add_item(ALEX, AddItemInput("oat milk", 2, "cartons"))
    assert msg.add_reply(out) == "Added **oat milk** — 2 cartons (Dairy)."

    await svc.add_item(ALEX, AddItemInput("apples", 2, "lb"))
    merged = await svc.add_item(ALEX, AddItemInput("Apples", 1, "lbs"))
    assert msg.add_reply(merged) == "Merged with existing **apples**: now 3 lb."

    again = await svc.add_item(ALEX, AddItemInput("milk"))
    assert "Added **milk** (Dairy)." in msg.add_reply(again)
    noop = await svc.add_item(ALEX, AddItemInput("MILK"))
    assert msg.add_reply(noop) == "**milk** is already on the list."

    other_unit = await svc.add_item(ALEX, AddItemInput("apples", 1, "bag"))
    assert "Also on the list: apples 3 lb" in msg.add_reply(other_unit)

    noted = await svc.add_item(ALEX, AddItemInput("milk", note="2%"))
    assert msg.add_reply(noted) == "Merged with existing **milk** (note updated)."


async def test_user_text_cannot_inject_markdown_or_mentions(svc):
    out = await svc.add_item(ALEX, AddItemInput("**bold** @everyone <@123456789012345678>"))
    text = msg.add_reply(out)
    assert "@everyone" not in text.replace("@​everyone", "")
    assert "<@123456789012345678>" not in text
    assert "\\*\\*bold\\*\\*" in text


async def test_addmany_reply_matches_the_spec_example(svc):
    result = await svc.add_many(ALEX, "eggs, 2 lb apples, paper towels")
    assert msg.addmany_reply(result) == (
        "Added 3: eggs (Dairy), apples 2 lb (Produce), paper towels (Household)."
    )
    again = await svc.add_many(ALEX, "1 lb apples, 0 gum")
    text = msg.addmany_reply(again)
    assert "Merged 1: apples → now 3 lb." in text
    assert "Couldn't add 1: “0 gum” (Quantity must be between 0.01 and 9999.)" in text


async def test_other_replies(svc):
    item = (await svc.add_item(ALEX, AddItemInput("apples", 3, "lb"))).item
    assert msg.check_reply([item]) == "Checked off **apples** — 3 lb."
    assert msg.check_reply([item, item]) == "Checked off 2 items."
    assert msg.remove_reply(item) == "Removed **apples**."
    checked = await svc.check_one(ALEX, item.id)
    back = await svc.uncheck_one(ALEX, checked.id)
    assert msg.uncheck_reply(back) == "Put **apples** — 3 lb back on the list."
    assert "(Produce)" in msg.edit_reply(back.item)


# ---- list rendering
async def test_list_groups_under_category_headings(svc):
    await svc.add_many(ALEX, "milk, 2 lb apples, soap")
    page = await svc.list_items(ALEX)
    text = msg.list_description(page)
    assert text.index("Produce") < text.index("Dairy") < text.index("Personal care")
    assert "• apples — 2 lb" in text
    assert msg.list_title(page) == "🛒 Grocery list — 3 needed"


async def test_empty_lists_have_helpful_text(svc):
    page = await svc.list_items(ALEX)
    assert "/grocery add" in msg.list_description(page)
    purchased = await svc.list_items(ALEX, "purchased")
    assert "Nothing has been checked off" in msg.list_description(purchased)


async def test_25_very_long_items_still_fit_in_an_embed(svc):
    long_name = "x" * 100
    for start in range(0, 25, 5):
        for n in range(start, start + 5):
            await svc.add_item(
                ALEX,
                AddItemInput(f"{long_name[:-3]}{n:03d}", 9999, "u" * 20, "produce", note="n" * 300),
            )
    page = await svc.list_items(ALEX, "all")
    assert len(page.items) == 25
    embed = msg.list_embed(page, "2:14 PM")
    assert len(embed.description) <= 4096
    assert len(embed) <= 6000  # Discord's limit for a whole embed
    assert embed.footer.text == "Page 1/1 · Updated 2:14 PM"


async def test_all_view_marks_purchased_items_and_shows_who_added(svc):
    item = (await svc.add_item(ALEX, AddItemInput("milk"))).item
    await svc.add_item(ALEX, AddItemInput("bread"))
    await svc.check_one(ALEX, item.id)
    text = msg.list_description(await svc.list_items(ALEX, "all"))
    assert "✔ ~~milk~~" in text and "• bread" in text
    assert f"added by <@{ALEX.user_id}>" in text


async def test_select_options_follow_the_view(svc):
    await svc.add_many(ALEX, "milk, eggs, bread")
    first = (await svc.list_items(ALEX)).items[0]
    await svc.check_one(ALEX, first.id)
    needed = await svc.list_items(ALEX, "all")
    assert len(msg.select_options(needed, "check")) == 2
    assert [o.value for o in msg.select_options(needed, "uncheck")] == [str(first.id)]


# ---- persistent components
def all_templates():
    return [
        GroceryNavButton.__discord_ui_compiled_template__,
        GroceryItemSelect.__discord_ui_compiled_template__,
        GroceryClearAsk.__discord_ui_compiled_template__,
    ]


async def test_list_view_ids_are_unique_valid_and_match_a_template(svc):
    await svc.add_many(ALEX, "milk, eggs, bread")
    first = (await svc.list_items(ALEX)).items[0]
    await svc.check_one(ALEX, first.id)
    for view_name in ("needed", "purchased", "all"):
        page = await svc.list_items(ALEX, view_name, "dairy" if view_name == "all" else None)
        view = build_list_view(page)
        assert view.is_finished()
        custom_ids = [c.custom_id for c in view.children]
        assert len(custom_ids) == len(set(custom_ids))  # Discord requires unique IDs per message
        for custom_id in custom_ids:
            assert len(custom_id) <= 100
            assert any(t.fullmatch(custom_id) for t in all_templates()), custom_id


async def test_navigation_buttons_are_disabled_at_the_ends(svc):
    await svc.add_many(ALEX, "milk, eggs")
    page = await svc.list_items(ALEX)
    by_kind = {c.kind: c for c in build_list_view(page).children if hasattr(c, "kind")}
    assert by_kind["prev"].item.disabled and by_kind["next"].item.disabled
    assert not by_kind["ref"].item.disabled


async def test_clear_button_only_appears_when_something_is_purchased(svc):
    await svc.add_item(ALEX, AddItemInput("milk"))
    assert not any(
        isinstance(c, GroceryClearAsk) for c in build_list_view(await svc.list_items(ALEX)).children
    )
    item = (await svc.list_items(ALEX)).items[0]
    await svc.check_one(ALEX, item.id)
    assert any(
        isinstance(c, GroceryClearAsk) for c in build_list_view(await svc.list_items(ALEX)).children
    )


async def click_select(ctx, custom_id, values, member=None):
    """Simulate what discord.py does for a select click after a bot restart."""
    inter = make_interaction(ctx, member)
    match = GroceryItemSelect.__discord_ui_compiled_template__.fullmatch(custom_id)
    item = await GroceryItemSelect.from_custom_id(inter, None, match)
    item._refresh_state(inter, {"values": values})
    await item.callback(inter)
    return inter


async def test_check_off_several_items_from_the_menu_then_the_list_refreshes(ctx, svc):
    await svc.add_many(ALEX, "milk, eggs, bread")
    page = await svc.list_items(ALEX)
    select = build_list_view(page).children[0]
    assert isinstance(select, GroceryItemSelect)
    chosen = [str(page.items[0].id), str(page.items[1].id)]
    inter = await click_select(ctx, select.custom_id, chosen)
    assert (await svc.list_items(ALEX, "needed")).total == 1
    assert (await svc.list_items(ALEX, "purchased")).total == 2
    (edit,) = inter.response.edits
    assert "1 needed" in edit["embed"].title
    assert edit["view"].is_finished()


async def test_the_menu_can_put_purchased_items_back(ctx, svc):
    await svc.add_many(ALEX, "milk, eggs")
    items = (await svc.list_items(ALEX)).items
    await svc.check_many(ALEX, [i.id for i in items])
    page = await svc.list_items(ALEX, "purchased")
    select = build_list_view(page).children[0]
    assert ":uncheck:" in select.custom_id
    await click_select(ctx, select.custom_id, [str(items[0].id)])
    assert (await svc.list_items(ALEX, "needed")).total == 1


async def test_nav_buttons_move_between_pages_and_views(ctx, svc):
    for start in range(0, 40, 20):
        await svc.add_many(ALEX, ",".join(f"item{n:02d}" for n in range(start, start + 20)))
    await svc.check_many(ALEX, [(await svc.list_items(ALEX)).items[0].id])
    page1 = await svc.list_items(ALEX)
    buttons = {c.kind: c for c in build_list_view(page1).children if hasattr(c, "kind")}

    async def press(button):
        inter = make_interaction(ctx)
        match = GroceryNavButton.__discord_ui_compiled_template__.fullmatch(button.custom_id)
        item = await GroceryNavButton.from_custom_id(inter, button.item, match)
        await item.callback(inter)
        return inter.response.edits[0]["embed"]

    assert "Page 2/2" in (await press(buttons["next"])).footer.text
    assert "Page 1/1" in (await press(buttons["view"])).footer.text  # purchased view
    assert "Page 1/2" in (await press(buttons["ref"])).footer.text


async def test_clicks_from_non_members_do_nothing(ctx, svc):
    await svc.add_item(ALEX, AddItemInput("milk"))
    item = (await svc.list_items(ALEX)).items[0]
    select = build_list_view(await svc.list_items(ALEX)).children[0]
    outsider = make_member(role_ids=(999,), user_id=66)
    inter = await click_select(ctx, select.custom_id, [str(item.id)], member=outsider)
    assert inter.response.sent[0][0] == NO_ACCESS
    assert (await svc.list_items(ALEX, "needed")).total == 1  # unchanged
    assert not inter.response.edits


async def test_clicks_in_another_server_do_nothing(ctx, svc):
    await svc.add_item(ALEX, AddItemInput("milk"))
    item = (await svc.list_items(ALEX)).items[0]
    select = build_list_view(await svc.list_items(ALEX)).children[0]
    inter = make_interaction(ctx, guild_id=GUILD_ID + 1)
    match = GroceryItemSelect.__discord_ui_compiled_template__.fullmatch(select.custom_id)
    sel = await GroceryItemSelect.from_custom_id(inter, None, match)
    sel._refresh_state(inter, {"values": [str(item.id)]})
    await sel.callback(inter)
    assert inter.response.sent[0][0] == NO_ACCESS
    assert (await svc.list_items(ALEX, "needed")).total == 1


# ---- clear with confirmation (US-G5)
async def press_confirm(ctx, view, which, member=None):
    button = view.children[0 if which == "yes" else 1]
    inter = make_interaction(ctx, member)
    match = ConfirmButton.__discord_ui_compiled_template__.fullmatch(button.custom_id)
    item = await ConfirmButton.from_custom_id(inter, button.item, match)
    await item.callback(inter)
    return inter


async def start_clear(ctx, svc, n_purchased=2):
    await svc.add_many(ALEX, "milk, eggs, bread")
    items = (await svc.list_items(ALEX)).items
    await svc.check_many(ALEX, [i.id for i in items[:n_purchased]])
    inter = make_interaction(ctx)
    await ask_clear(inter, ALEX)
    (text, kwargs) = inter.response.sent[0]
    return text, kwargs


async def test_us_g5_clear_asks_first_and_names_the_count(ctx, svc):
    text, kwargs = await start_clear(ctx, svc)
    assert text == "Remove **2** purchased items? This can't be undone."
    assert kwargs["ephemeral"] is True
    labels = [c.item.label for c in kwargs["view"].children]
    assert labels == ["Clear 2 items", "Cancel"]
    assert (await svc.list_items(ALEX, "purchased")).total == 2  # nothing deleted yet


async def test_us_g5_confirm_deletes_only_after_yes(ctx, svc):
    _, kwargs = await start_clear(ctx, svc)
    inter = await press_confirm(ctx, kwargs["view"], "yes")
    assert inter.response.edits[0]["content"] == "Cleared 2 purchased items."
    page = await svc.list_items(ALEX, "all")
    assert page.total == 1 and page.items[0].status == "needed"


async def test_us_g5_cancel_deletes_nothing(ctx, svc):
    _, kwargs = await start_clear(ctx, svc)
    inter = await press_confirm(ctx, kwargs["view"], "no")
    assert inter.response.edits[0]["content"] == "Cancelled."
    assert (await svc.list_items(ALEX, "purchased")).total == 2


async def test_us_g5_someone_elses_confirmation_does_nothing(ctx, svc):
    _, kwargs = await start_clear(ctx, svc)
    sam = make_member(user_id=99)
    inter = await press_confirm(ctx, kwargs["view"], "yes", member=sam)
    assert inter.response.sent[0][0] == NOT_YOURS
    assert (await svc.list_items(ALEX, "purchased")).total == 2


async def test_us_g5_confirmation_expires_after_two_minutes(ctx, svc, clock):
    _, kwargs = await start_clear(ctx, svc)
    clock.advance(seconds=121)
    inter = await press_confirm(ctx, kwargs["view"], "yes")
    assert inter.response.edits[0]["content"] == EXPIRED
    assert (await svc.list_items(ALEX, "purchased")).total == 2


async def test_confirmation_fails_safely_if_the_list_changed(ctx, svc):
    _, kwargs = await start_clear(ctx, svc)
    extra = (await svc.list_items(ALEX, "needed")).items[0]
    await svc.check_one(ALEX, extra.id)  # now 3 purchased, but 2 were confirmed
    inter = await press_confirm(ctx, kwargs["view"], "yes")
    assert "changed" in inter.response.sent[0][0]
    assert (await svc.list_items(ALEX, "purchased")).total == 3


async def test_clear_with_nothing_purchased_says_so(ctx, svc):
    inter = make_interaction(ctx)
    await ask_clear(inter, ALEX)
    assert "no purchased items" in inter.response.sent[0][0]


# ---- commands
def test_command_group_has_every_subcommand_and_documented_options():
    from types import SimpleNamespace

    group = build_grocery_group(SimpleNamespace())
    assert group.guild_only
    commands = {c.name: {p.name for p in c.parameters} for c in group.commands}
    assert commands == {
        "add": {"item", "quantity", "unit", "category", "note"},
        "addmany": {"items"},
        "list": {"view", "category", "share"},
        "check": {"item"},
        "uncheck": {"item"},
        "edit": {"item", "name", "quantity", "unit", "category", "note", "clear"},
        "remove": {"item"},
        "clear": set(),
    }
    add = next(c for c in group.commands if c.name == "add")
    required = {p.name for p in add.parameters if p.required}
    assert required == {"item"}
    for cmd in group.commands:
        item = next((p for p in cmd.parameters if p.name == "item"), None)
        if item is not None and cmd.name != "add":
            assert item.autocomplete  # pick from the list instead of typing IDs


def test_unit_suggestions():
    assert "lb" in unit_matches("l")
    assert unit_matches("zzz") == []
    assert len(unit_matches("")) <= 25


async def test_item_autocomplete_is_private_to_members(ctx, svc):
    await svc.add_many(ALEX, "oat milk, eggs")
    bot = type("B", (), {"ctx": ctx})()
    group = build_grocery_group(bot)
    check = next(c for c in group.commands if c.name == "check")
    autocomplete = check._params["item"].autocomplete  # the callback discord.py will run

    member_inter = make_interaction(ctx)
    choices = await autocomplete(member_inter, "milk")
    assert [(c.name, c.value) for c in choices] == [
        ("oat milk", str((await svc.search(ALEX, "milk"))[0].id))
    ]

    outsider = make_interaction(ctx, make_member(role_ids=(999,)))
    assert await autocomplete(outsider, "milk") == []
    other_guild = make_interaction(ctx, guild_id=GUILD_ID + 1)
    assert await autocomplete(other_guild, "milk") == []


async def test_render_list_gives_embed_and_finished_view(ctx, svc):
    await svc.add_many(ALEX, "milk, eggs")
    embed, view = await render_list(ctx, ALEX, "needed", None, 1)
    assert "2 needed" in embed.title
    assert re.search(r"Updated \d{1,2}:\d{2} (AM|PM)", embed.footer.text)
    assert view.is_finished()
