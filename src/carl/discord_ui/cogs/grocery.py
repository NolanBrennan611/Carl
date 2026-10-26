"""/grocery add | addmany | list | check | uncheck | edit | remove | clear
(docs/discord-commands.md section 4)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from carl.discord_ui import grocery_messages as msg
from carl.discord_ui.components.base import autocomplete_actor
from carl.discord_ui.components.grocery import ask_clear, render_list
from carl.discord_ui.responses import NO_MENTIONS, respond, respond_brief
from carl.domain.grocery import COMMON_UNITS, quantity_text
from carl.services.grocery_service import AddItemInput, EditItemInput

if TYPE_CHECKING:
    from carl.discord_ui.bot import CarlBot

log = logging.getLogger("carl.grocery")

CATEGORY_CHOICES = [
    app_commands.Choice(name=label, value=value) for label, value in msg.category_choices()
]
VIEW_CHOICES = [
    app_commands.Choice(name="Needed (default)", value="needed"),
    app_commands.Choice(name="Purchased", value="purchased"),
    app_commands.Choice(name="Everything", value="all"),
]
CLEAR_CHOICES = [
    app_commands.Choice(name="Note", value="note"),
    app_commands.Choice(name="Quantity", value="quantity"),
    app_commands.Choice(name="Unit", value="unit"),
]


def _choice_label(item) -> str:
    qty = quantity_text(item.quantity, item.unit)
    text = f"{item.name} — {qty}" if qty else item.name
    if item.status == "purchased":
        text = f"✔ {text}"
    return text if len(text) <= 100 else text[:99] + "…"


def unit_matches(current: str, limit: int = 25) -> list[str]:
    needle = current.strip().casefold()
    return [u for u in COMMON_UNITS if needle in u][:limit]


def build_grocery_group(bot: CarlBot) -> app_commands.Group:
    group = app_commands.Group(
        name="grocery", description="The shared grocery list", guild_only=True
    )

    async def _make_live(
        interaction: discord.Interaction, view_name: str, category_name: str | None
    ) -> None:
        """Remember the message we just posted as the live list (best effort)."""
        try:
            posted = await interaction.original_response()
            await bot.live_list.replace(
                posted.channel.id, posted.id, view=view_name, category=category_name
            )
        except Exception:  # noqa: BLE001 - the list itself was delivered; this is a bonus
            log.exception("could_not_make_live_list")

    def item_autocomplete(view: str):
        async def autocomplete(
            interaction: discord.Interaction, current: str
        ) -> list[app_commands.Choice[str]]:
            actor = autocomplete_actor(interaction)
            if actor is None:
                return []
            try:
                items = await bot.ctx.grocery_service.search(actor, current, view)
            except Exception:  # noqa: BLE001 - autocomplete must never raise
                log.exception("autocomplete_failed")
                return []
            return [app_commands.Choice(name=_choice_label(i), value=str(i.id)) for i in items]

        return autocomplete

    # ---- add
    @group.command(name="add", description="Add an item to the list")
    @app_commands.describe(
        item="What to buy, e.g. oat milk",
        quantity="How many (optional)",
        unit="Unit, e.g. lb, gal, bag (optional)",
        category="Aisle (guessed from the name if you skip it)",
        note="Extra detail, e.g. unsweetened",
    )
    @app_commands.choices(category=CATEGORY_CHOICES)
    async def add_cmd(
        interaction: discord.Interaction,
        item: app_commands.Range[str, 1, 100],
        quantity: app_commands.Range[float, 0.01, 9999.0] | None = None,
        unit: app_commands.Range[str, 1, 20] | None = None,
        category: app_commands.Choice[str] | None = None,
        note: app_commands.Range[str, 1, 300] | None = None,
    ) -> None:
        actor = interaction.extras["actor"]
        outcome = await bot.ctx.grocery_service.add_item(
            actor,
            AddItemInput(item, quantity, unit, category.value if category else None, note),
        )
        await respond_brief(interaction, msg.add_reply(outcome))
        if outcome.changed:
            await bot.live_list.refresh_after(interaction)

    @add_cmd.autocomplete("unit")
    async def unit_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return [app_commands.Choice(name=u, value=u) for u in unit_matches(current)]

    # ---- addmany
    @group.command(name="addmany", description="Add several items at once, separated by commas")
    @app_commands.describe(items="e.g. milk, 2 lb apples, 3 cans tomatoes (max 20)")
    async def addmany_cmd(
        interaction: discord.Interaction, items: app_commands.Range[str, 1, 1000]
    ) -> None:
        actor = interaction.extras["actor"]
        result = await bot.ctx.grocery_service.add_many(actor, items)
        text = msg.addmany_reply(result)
        if result.of("rejected"):
            await respond(interaction, text)  # problems stay on screen until read
        else:
            await respond_brief(interaction, text)
        if result.of("added") or result.of("merged"):
            await bot.live_list.refresh_after(interaction)

    # ---- list
    @group.command(name="list", description="Show the grocery list")
    @app_commands.describe(
        view="Which items to show",
        category="Only this aisle",
        share="Post the list for everyone and keep it up to date (default: yes)",
    )
    @app_commands.choices(view=VIEW_CHOICES, category=CATEGORY_CHOICES)
    async def list_cmd(
        interaction: discord.Interaction,
        view: app_commands.Choice[str] | None = None,
        category: app_commands.Choice[str] | None = None,
        share: bool = True,
    ) -> None:
        actor = interaction.extras["actor"]
        view_name = view.value if view else "needed"
        category_name = category.value if category else None
        embed, components = await render_list(bot.ctx, actor, view_name, category_name, 1)
        await interaction.response.send_message(
            embed=embed, view=components, ephemeral=not share, allowed_mentions=NO_MENTIONS
        )
        if share:
            await _make_live(interaction, view_name, category_name)

    # ---- check / uncheck
    @group.command(name="check", description="Check an item off")
    @app_commands.describe(item="The item you bought")
    async def check_cmd(interaction: discord.Interaction, item: str) -> None:
        actor = interaction.extras["actor"]
        svc = bot.ctx.grocery_service
        found = await svc.resolve(actor, item, "needed")
        checked = await svc.check_one(actor, found.id)
        await respond_brief(interaction, msg.check_reply([checked]))
        await bot.live_list.refresh_after(interaction)

    check_cmd.autocomplete("item")(item_autocomplete("needed"))

    @group.command(name="uncheck", description="Put a checked-off item back on the list")
    @app_commands.describe(item="The item to put back")
    async def uncheck_cmd(interaction: discord.Interaction, item: str) -> None:
        actor = interaction.extras["actor"]
        svc = bot.ctx.grocery_service
        found = await svc.resolve(actor, item, "purchased")
        outcome = await svc.uncheck_one(actor, found.id)
        await respond_brief(interaction, msg.uncheck_reply(outcome))
        await bot.live_list.refresh_after(interaction)

    uncheck_cmd.autocomplete("item")(item_autocomplete("purchased"))

    # ---- edit
    @group.command(name="edit", description="Change an item")
    @app_commands.describe(
        item="The item to change",
        name="New name",
        quantity="New quantity",
        unit="New unit",
        category="New aisle",
        note="New note",
        clear="Remove one of these details",
    )
    @app_commands.choices(category=CATEGORY_CHOICES, clear=CLEAR_CHOICES)
    async def edit_cmd(
        interaction: discord.Interaction,
        item: str,
        name: app_commands.Range[str, 1, 100] | None = None,
        quantity: app_commands.Range[float, 0.01, 9999.0] | None = None,
        unit: app_commands.Range[str, 1, 20] | None = None,
        category: app_commands.Choice[str] | None = None,
        note: app_commands.Range[str, 1, 300] | None = None,
        clear: app_commands.Choice[str] | None = None,
    ) -> None:
        actor = interaction.extras["actor"]
        svc = bot.ctx.grocery_service
        found = await svc.resolve(actor, item, "all")
        updated = await svc.edit(
            actor,
            found.id,
            EditItemInput(
                name=name,
                quantity=quantity,
                unit=unit,
                category=category.value if category else None,
                note=note,
                clear=frozenset({clear.value}) if clear else frozenset(),
            ),
        )
        await respond_brief(interaction, msg.edit_reply(updated))
        await bot.live_list.refresh_after(interaction)

    edit_cmd.autocomplete("item")(item_autocomplete("all"))

    # ---- remove
    @group.command(name="remove", description="Delete an item from the list")
    @app_commands.describe(item="The item to remove")
    async def remove_cmd(interaction: discord.Interaction, item: str) -> None:
        actor = interaction.extras["actor"]
        svc = bot.ctx.grocery_service
        found = await svc.resolve(actor, item, "all")
        removed = await svc.remove(actor, found.id)
        await respond_brief(interaction, msg.remove_reply(removed))
        await bot.live_list.refresh_after(interaction)

    remove_cmd.autocomplete("item")(item_autocomplete("all"))

    # ---- clear
    @group.command(name="clear", description="Remove all checked-off items (asks first)")
    async def clear_cmd(interaction: discord.Interaction) -> None:
        await ask_clear(interaction, interaction.extras["actor"])

    return group
