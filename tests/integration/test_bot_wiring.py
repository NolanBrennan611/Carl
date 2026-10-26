"""Exercise CarlTree/CarlBot without connecting to Discord, using stub interactions."""

from types import SimpleNamespace

import discord
from discord import app_commands

from carl.discord_ui.auth import NO_ACCESS
from carl.discord_ui.bot import CarlBot, CarlTree, respond
from carl.discord_ui.command_sync import STATE_KEY, command_hash, sync_if_changed
from carl.domain.errors import Forbidden, ValidationError
from tests.conftest import ADMIN_ROLE_ID, GUILD_ID, ROLE_ID

CMD = SimpleNamespace(name="stub")


class StubResponse:
    def __init__(self):
        self.sent = []
        self.done = False

    def is_done(self):
        return self.done

    async def send_message(self, content=None, **kwargs):
        self.done = True
        self.sent.append((content, kwargs))


class StubFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


def interaction(role_ids, guild_id=GUILD_ID):
    user = SimpleNamespace(
        id=7,
        roles=[SimpleNamespace(id=r) for r in role_ids],
        guild_permissions=SimpleNamespace(manage_guild=False),
    )
    return SimpleNamespace(
        guild_id=guild_id, user=user, extras={}, response=StubResponse(), followup=StubFollowup()
    )


async def test_outsider_is_blocked_before_any_command_runs(ctx):
    tree = CarlBot(ctx).tree
    inter = interaction([999])
    assert await tree.interaction_check(inter) is False
    assert inter.response.sent == [(NO_ACCESS, {"ephemeral": True})]
    assert "actor" not in inter.extras


async def test_wrong_guild_is_blocked(ctx):
    inter = interaction([ROLE_ID], guild_id=GUILD_ID + 1)
    assert await CarlBot(ctx).tree.interaction_check(inter) is False
    assert inter.response.sent[0][0] == NO_ACCESS


async def test_member_passes_and_actor_is_attached(ctx):
    inter = interaction([ROLE_ID, ADMIN_ROLE_ID])
    assert await CarlBot(ctx).tree.interaction_check(inter) is True
    actor = inter.extras["actor"]
    assert (actor.guild_id, actor.user_id, actor.is_admin) == (GUILD_ID, 7, True)


async def test_errors_become_ephemeral_messages(ctx):
    tree = CarlBot(ctx).tree
    inter = interaction([ROLE_ID])
    await tree.on_error(inter, app_commands.CommandInvokeError(CMD, ValidationError("Bad input.")))
    assert inter.response.sent == [("Bad input.", {"ephemeral": True})]

    inter = interaction([ROLE_ID])
    await tree.on_error(inter, app_commands.CommandInvokeError(CMD, Forbidden("Admins only.")))
    assert inter.response.sent[0][0] == "Admins only."

    inter = interaction([ROLE_ID])
    await tree.on_error(inter, app_commands.CommandInvokeError(CMD, RuntimeError("db secret")))
    text = inter.response.sent[0][0]
    assert "db secret" not in text and "ref `E-" in text


async def test_respond_uses_followup_when_already_answered():
    inter = interaction([])
    inter.response.done = True
    await respond(inter, "hello")
    assert inter.followup.sent == [("hello", {"ephemeral": True})]
    assert inter.response.sent == []


async def test_bot_is_guilds_only_and_starts_not_ready(ctx):
    bot = CarlBot(ctx)
    try:
        assert bot.intents.guilds and not bot.intents.message_content
        assert bot.started_at == ctx.clock.now()
    finally:
        await bot.close()


async def test_bot_tree_is_the_guarded_tree(ctx):
    bot = CarlBot(ctx)
    try:
        assert isinstance(bot.tree, CarlTree)
    finally:
        await bot.close()


async def test_commands_sync_only_when_definitions_change(ctx, monkeypatch):
    from carl.discord_ui.cogs.admin import build_carl_group

    bot = CarlBot(ctx)
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.add_command(build_carl_group(bot), guild=guild)
        syncs = []

        async def fake_sync(*, guild):
            syncs.append(guild.id)
            return []

        monkeypatch.setattr(bot.tree, "sync", fake_sync)

        assert await sync_if_changed(bot.tree, guild, ctx.app_state, "2026-10-25T12:00:00.000Z")
        assert not await sync_if_changed(bot.tree, guild, ctx.app_state, "2026-10-25T12:00:01.000Z")
        assert syncs == [GUILD_ID]
        assert await ctx.app_state.get(STATE_KEY) == command_hash(bot.tree, guild)

        await ctx.app_state.set(STATE_KEY, "stale", "2026-10-25T12:00:02.000Z")
        assert await sync_if_changed(bot.tree, guild, ctx.app_state, "2026-10-25T12:00:03.000Z")
        assert syncs == [GUILD_ID, GUILD_ID]
    finally:
        await bot.close()
