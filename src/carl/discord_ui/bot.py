"""CarlBot: Discord Gateway client locked to one household guild."""

from __future__ import annotations

import logging
from collections.abc import Iterable

import discord
from discord import app_commands

from carl.app import AppContext
from carl.discord_ui import errors
from carl.discord_ui.auth import resolve_actor
from carl.discord_ui.cogs.admin import build_carl_group
from carl.discord_ui.cogs.grocery import build_grocery_group
from carl.discord_ui.command_sync import sync_if_changed
from carl.discord_ui.components.confirm import ConfirmButton
from carl.discord_ui.components.grocery import DYNAMIC_ITEMS as GROCERY_ITEMS
from carl.discord_ui.live_list import LiveList
from carl.discord_ui.responses import respond
from carl.domain import timeutil
from carl.domain.errors import CarlError

log = logging.getLogger("carl.bot")


def build_intents() -> discord.Intents:
    """GUILDS only. No privileged intents (message content, members, presences)."""
    intents = discord.Intents.none()
    intents.guilds = True
    return intents


def foreign_guild_ids(guild_ids: Iterable[int], home_id: int) -> list[int]:
    return [g for g in guild_ids if g != home_id]


class CarlTree(app_commands.CommandTree):
    def __init__(self, bot: CarlBot) -> None:
        super().__init__(bot)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Runs before every slash command: only household Members get through."""
        try:
            interaction.extras["actor"] = resolve_actor(
                interaction.guild_id, interaction.user, self.bot.ctx.settings
            )
        except CarlError as exc:
            await respond(interaction, exc.message)
            return False
        return True

    async def on_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
        message = errors.message_for(original)
        try:
            await respond(interaction, message)
        except discord.HTTPException:
            log.warning("could_not_send_error_reply")


class CarlBot(discord.Client):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(intents=build_intents())
        self.ctx = ctx
        self.tree = CarlTree(self)
        self.live_list = LiveList(ctx, self.get_partial_messageable)
        self.started_at = ctx.clock.now()

    async def setup_hook(self) -> None:
        guild = discord.Object(id=self.ctx.settings.guild_id)
        self.add_dynamic_items(ConfirmButton, *GROCERY_ITEMS)
        self.tree.add_command(build_carl_group(self), guild=guild)
        self.tree.add_command(build_grocery_group(self), guild=guild)
        now = timeutil.to_db_instant(timeutil.utc_now(self.ctx.clock))
        await sync_if_changed(self.tree, guild, self.ctx.app_state, now)

    async def on_ready(self) -> None:
        log.info("ready user_id=%s guilds=%d", self.user.id if self.user else 0, len(self.guilds))
        await self._leave_foreign_guilds()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        if guild.id != self.ctx.settings.guild_id:
            log.warning("foreign_guild_joined guild_id=%d leaving", guild.id)
            await guild.leave()

    async def _leave_foreign_guilds(self) -> None:
        by_id = {g.id: g for g in self.guilds}
        for guild_id in foreign_guild_ids(by_id, self.ctx.settings.guild_id):
            log.warning("foreign_guild_found guild_id=%d leaving", guild_id)
            await by_id[guild_id].leave()
