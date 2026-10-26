"""Interactive grocery list: page buttons, multi-select, and the "clear purchased" prompt.

All items are persistent DynamicItems, so they keep working after a restart. Views built here
are stopped right away (see `finish`) so discord.py doesn't also keep them in memory, which
would run each click twice.
"""

from __future__ import annotations

import re

import discord

from carl.app import AppContext
from carl.discord_ui.components import ids
from carl.discord_ui.components.base import app_context, guard
from carl.discord_ui.components.confirm import build_confirm_view, register_confirm_handler
from carl.discord_ui.grocery_messages import list_embed, select_options
from carl.discord_ui.responses import respond
from carl.domain import timeutil
from carl.domain.formatting import format_clock
from carl.domain.models import Actor
from carl.services.grocery_service import GroceryPage

_VIEW = r"(?P<view>needed|purchased|all)"
_CAT = r"(?P<cat>[a-z_]+)"
_PAGE = r"(?P<page>\d+)"
CLEAR_ACTION = "gclear"


def finish(view: discord.ui.View) -> discord.ui.View:
    view.stop()
    return view


# ---- rendering
async def render_list(
    ctx: AppContext, actor: Actor, view: str, category: str | None, page: int
) -> tuple[discord.Embed, discord.ui.View]:
    pg = await ctx.grocery_service.list_items(actor, view, category, page)
    settings = await ctx.settings_service.get(actor.guild_id)
    local_now = timeutil.utc_now(ctx.clock).astimezone(timeutil.get_zone(settings.timezone))
    return list_embed(pg, format_clock(local_now)), build_list_view(pg)


def build_list_view(pg: GroceryPage) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    mode = "uncheck" if pg.view == "purchased" else "check"
    options = select_options(pg, mode)
    if options:
        view.add_item(GroceryItemSelect(mode, pg.view, pg.category, pg.page, options=options))
    view.add_item(
        GroceryNavButton("prev", pg.view, pg.category, pg.page, label="◀", disabled=pg.page <= 1)
    )
    view.add_item(
        GroceryNavButton(
            "next", pg.view, pg.category, pg.page, label="▶", disabled=pg.page >= pg.pages
        )
    )
    view.add_item(GroceryNavButton("ref", pg.view, pg.category, pg.page, label="↻"))
    if pg.view == "needed":
        toggle = f"Show purchased ({pg.purchased_count})"
    else:
        toggle = f"Show needed ({pg.needed_count})"
    view.add_item(GroceryNavButton("view", pg.view, pg.category, pg.page, label=toggle))
    if pg.purchased_count:
        view.add_item(GroceryClearAsk())
    return finish(view)


# ---- page / refresh / toggle buttons
class GroceryNavButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=rf"carl:v1:gl:go:(?P<k>prev|next|ref|view):{_VIEW}:{_CAT}:{_PAGE}",
):
    def __init__(
        self,
        kind: str,
        view: str,
        category: str | None,
        page: int,
        *,
        label: str,
        disabled: bool = False,
    ) -> None:
        self.kind, self.list_view, self.category, self.page = kind, view, category, page
        super().__init__(
            discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                disabled=disabled,
                custom_id=ids.build("gl", "go", kind, view, ids.cat_token(category), page),
            ),
            row=1,
        )

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> GroceryNavButton:
        return cls(
            match["k"],
            match["view"],
            ids.cat_from_token(match["cat"]),
            int(match["page"]),
            label=item.label or "",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await guard(interaction, lambda actor: self._handle(interaction, actor))

    async def _handle(self, interaction: discord.Interaction, actor: Actor) -> None:
        view, page = self.list_view, self.page
        if self.kind == "prev":
            page -= 1
        elif self.kind == "next":
            page += 1
        elif self.kind == "view":
            view, page = ("purchased" if self.list_view == "needed" else "needed"), 1
        embed, new_view = await render_list(
            app_context(interaction), actor, view, self.category, page
        )
        await interaction.response.edit_message(embed=embed, view=new_view)


# ---- multi-select: check off / put back
class GroceryItemSelect(
    discord.ui.DynamicItem[discord.ui.Select],
    template=rf"carl:v1:gl:sel:(?P<mode>check|uncheck):{_VIEW}:{_CAT}:{_PAGE}",
):
    def __init__(
        self,
        mode: str,
        view: str,
        category: str | None,
        page: int,
        *,
        options: list[discord.SelectOption],
    ) -> None:
        self.mode, self.list_view, self.category, self.page = mode, view, category, page
        placeholder = "✔ Check off items…" if mode == "check" else "↩ Put items back…"
        super().__init__(
            discord.ui.Select(
                custom_id=ids.build("gl", "sel", mode, view, ids.cat_token(category), page),
                placeholder=placeholder,
                min_values=1,
                max_values=max(1, len(options)),
                options=options,
            ),
            row=0,
        )

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Select, match: re.Match[str], /
    ) -> GroceryItemSelect:
        # Options aren't needed to handle a click; the chosen values come with the interaction.
        return cls(
            match["mode"],
            match["view"],
            ids.cat_from_token(match["cat"]),
            int(match["page"]),
            options=[],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await guard(interaction, lambda actor: self._handle(interaction, actor))

    async def _handle(self, interaction: discord.Interaction, actor: Actor) -> None:
        ctx = app_context(interaction)
        chosen = [int(v) for v in self.item.values if v.isdigit()]
        if self.mode == "check":
            await ctx.grocery_service.check_many(actor, chosen)
        else:
            await ctx.grocery_service.uncheck_many(actor, chosen)
        embed, new_view = await render_list(ctx, actor, self.list_view, self.category, self.page)
        await interaction.response.edit_message(embed=embed, view=new_view)


# ---- clear purchased (with confirmation)
async def ask_clear(interaction: discord.Interaction, actor: Actor) -> None:
    """Ask "Remove N purchased items?" in a private message with Confirm / Cancel buttons."""
    ctx = app_context(interaction)
    count = await ctx.grocery_service.count_purchased(actor)
    if count == 0:
        await respond(interaction, "There are no purchased items to clear.")
        return
    noun = "item" if count == 1 else "items"
    view = build_confirm_view(
        CLEAR_ACTION,
        count,
        actor.user_id,
        ctx.clock.now().timestamp(),
        yes_label=f"Clear {count} {noun}",
    )
    await interaction.response.send_message(
        f"Remove **{count}** purchased {noun}? This can't be undone.", view=view, ephemeral=True
    )


class GroceryClearAsk(discord.ui.DynamicItem[discord.ui.Button], template=r"carl:v1:gl:clearask"):
    def __init__(self) -> None:
        super().__init__(
            discord.ui.Button(
                label="Clear purchased…",
                style=discord.ButtonStyle.danger,
                custom_id=ids.build("gl", "clearask"),
            ),
            row=2,
        )

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> GroceryClearAsk:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        await guard(interaction, lambda actor: ask_clear(interaction, actor))


async def _confirm_clear(interaction: discord.Interaction, actor: Actor, expected: int) -> str:
    cleared = await app_context(interaction).grocery_service.clear_purchased(
        actor, expected_count=expected
    )
    return f"Cleared {cleared} purchased {'item' if cleared == 1 else 'items'}."


register_confirm_handler(CLEAR_ACTION, _confirm_clear)

DYNAMIC_ITEMS = (GroceryNavButton, GroceryItemSelect, GroceryClearAsk)
