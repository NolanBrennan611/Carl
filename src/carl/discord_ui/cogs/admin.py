"""/carl help | settings | setup | status (docs/discord-commands.md section 11)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import available_timezones

import discord
from discord import app_commands

from carl import __version__
from carl.discord_ui import embeds
from carl.discord_ui.auth import require_admin
from carl.domain.errors import ValidationError

if TYPE_CHECKING:
    from carl.discord_ui.bot import CarlBot

_ZONES = sorted(available_timezones())
_REQUIRED_CHANNEL_PERMS = ("view_channel", "send_messages", "embed_links")


def timezone_matches(current: str, limit: int = 25) -> list[str]:
    """Time zone names containing the typed text (case-insensitive, '_' and ' ' equal)."""
    needle = current.strip().lower().replace(" ", "_")
    if not needle:
        return [z for z in _ZONES if z.startswith("America/")][:limit]
    return [z for z in _ZONES if needle in z.lower()][:limit]


def format_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def build_carl_group(bot: CarlBot) -> app_commands.Group:
    group = app_commands.Group(
        name="carl",
        description="Carl settings and help",
        guild_only=True,
    )

    @group.command(name="help", description="What Carl can do")
    async def help_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=embeds.help_embed(), ephemeral=True)

    @group.command(name="settings", description="Show the household settings")
    async def settings_cmd(interaction: discord.Interaction) -> None:
        current = await bot.ctx.settings_service.get(bot.ctx.settings.guild_id)
        await interaction.response.send_message(
            embed=embeds.settings_embed(current), ephemeral=True
        )

    @group.command(name="setup", description="Admins: set time zone, reminder channel and times")
    @app_commands.describe(
        channel="Channel where household reminders are posted",
        timezone="Household time zone, e.g. America/Chicago",
        reminder_time="Time of day for reminders, HH:MM (24-hour)",
        currency="Default currency, e.g. USD",
        default_remind="Default bill reminder days before due, e.g. 3,0",
        date_order="How typed dates like 11/5 are read",
    )
    @app_commands.choices(
        date_order=[
            app_commands.Choice(name="Month/Day (11/5 = Nov 5)", value="MDY"),
            app_commands.Choice(name="Day/Month (11/5 = May 11)", value="DMY"),
        ]
    )
    async def setup_cmd(
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        timezone: str | None = None,
        reminder_time: str | None = None,
        currency: str | None = None,
        default_remind: str | None = None,
        date_order: app_commands.Choice[str] | None = None,
    ) -> None:
        actor = require_admin(interaction.extras["actor"])
        if channel is not None and interaction.guild is not None:
            perms = channel.permissions_for(interaction.guild.me)
            missing = [
                p.replace("_", " ") for p in _REQUIRED_CHANNEL_PERMS if not getattr(perms, p)
            ]
            if missing:
                raise ValidationError(
                    f"I can't post in {channel.mention}. Give me these permissions there: "
                    + ", ".join(missing)
                    + "."
                )
        provided = {
            "channel": channel,
            "timezone": timezone,
            "reminder time": reminder_time,
            "currency": currency,
            "default reminders": default_remind,
            "date order": date_order,
        }
        changed = [name for name, value in provided.items() if value is not None]
        updated = await bot.ctx.settings_service.setup(
            actor,
            reminder_channel_id=channel.id if channel else None,
            timezone=timezone,
            reminder_time=reminder_time,
            currency=currency,
            default_remind=default_remind,
            date_order=date_order.value if date_order else None,
        )
        await interaction.response.send_message(
            embed=embeds.setup_result_embed(updated, changed), ephemeral=True
        )

    @setup_cmd.autocomplete("timezone")
    async def timezone_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return [app_commands.Choice(name=z, value=z) for z in timezone_matches(current)]

    @group.command(name="status", description="Admins: bot health overview")
    async def status_cmd(interaction: discord.Interaction) -> None:
        require_admin(interaction.extras["actor"])
        ctx = bot.ctx
        now = ctx.clock.now()
        try:
            size_mb = ctx.settings.db_path.stat().st_size / (1024 * 1024)
            db_size = f"{size_mb:.2f} MB"
        except OSError:
            db_size = "unknown"
        latency = bot.latency
        e = discord.Embed(title="Carl status", color=embeds.COLOR)
        e.add_field(name="Version", value=__version__)
        e.add_field(name="Uptime", value=format_uptime((now - bot.started_at).total_seconds()))
        e.add_field(
            name="Gateway latency",
            value="n/a" if latency != latency else f"{latency * 1000:.0f} ms",  # NaN check
        )
        e.add_field(name="Database size", value=db_size)
        await interaction.response.send_message(embed=e, ephemeral=True)

    return group
