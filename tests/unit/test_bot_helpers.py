import discord
from discord import app_commands

from carl.discord_ui.bot import build_intents, foreign_guild_ids
from carl.discord_ui.cogs.admin import format_uptime, timezone_matches
from carl.discord_ui.command_sync import command_hash
from carl.discord_ui.errors import message_for
from carl.domain.errors import Conflict, NotFound


def test_intents_are_guilds_only_with_no_privileged_intents():
    intents = build_intents()
    assert intents.value == discord.Intents.none().value | discord.Intents(guilds=True).value
    assert intents.guilds
    for privileged in ("message_content", "members", "presences"):
        assert not getattr(intents, privileged)
    assert not intents.messages and not intents.guild_messages and not intents.dm_messages


def test_foreign_guild_detection():
    assert foreign_guild_ids([1, 2, 3], home_id=2) == [1, 3]
    assert foreign_guild_ids([2], home_id=2) == []
    assert foreign_guild_ids([], home_id=2) == []


def test_timezone_autocomplete():
    assert "America/Chicago" in timezone_matches("chicago")
    assert "America/New_York" in timezone_matches("new york")
    assert len(timezone_matches("a")) <= 25
    default = timezone_matches("")
    assert default and all(z.startswith("America/") for z in default)
    assert timezone_matches("zzzzzz") == []


def test_uptime_formatting():
    assert format_uptime(59) == "0m"
    assert format_uptime(3 * 3600 + 5 * 60) == "3h 5m"
    assert format_uptime(2 * 86400 + 3600) == "2d 1h 0m"


def test_carl_errors_show_their_message_and_unexpected_ones_do_not_leak():
    assert message_for(NotFound("That task wasn't found.")) == "That task wasn't found."
    assert message_for(Conflict("Already exists.")) == "Already exists."
    text = message_for(RuntimeError("secret internals: token=abc"))
    assert "secret" not in text and "ref `E-" in text


class _Stub(discord.Client):
    pass


def _tree_with_command(description):
    client = _Stub(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)
    guild = discord.Object(id=1000)
    group = app_commands.Group(name="carl", description=description, guild_only=True)

    @group.command(name="help", description="Help")
    async def help_cmd(interaction: discord.Interaction) -> None: ...

    tree.add_command(group, guild=guild)
    return tree, guild


def test_command_hash_is_stable_and_detects_changes():
    tree_a, guild = _tree_with_command("Carl settings")
    tree_b, _ = _tree_with_command("Carl settings")
    tree_c, _ = _tree_with_command("Something else")
    assert command_hash(tree_a, guild) == command_hash(tree_b, guild)
    assert command_hash(tree_a, guild) != command_hash(tree_c, guild)


def test_real_command_group_registers_expected_subcommands():
    from types import SimpleNamespace

    from carl.discord_ui.cogs.admin import build_carl_group

    group = build_carl_group(SimpleNamespace())  # handlers only touch the bot when invoked
    names = {c.name for c in group.commands}
    assert names == {"help", "settings", "setup", "status"}
    assert group.guild_only
    setup = next(c for c in group.commands if c.name == "setup")
    assert {p.name for p in setup.parameters} == {
        "channel", "timezone", "reminder_time", "currency", "default_remind", "date_order",
    }  # fmt: skip
    assert all(not p.required for p in setup.parameters)
