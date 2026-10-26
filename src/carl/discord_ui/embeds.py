"""Render view data into Discord embeds."""

from __future__ import annotations

import discord

from carl.domain.models import GuildSettings

COLOR = discord.Color.blurple()

_SUMMARY_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def help_embed() -> discord.Embed:
    e = discord.Embed(title="Carl help", color=COLOR)
    e.description = (
        "Carl keeps your household's grocery list, to-dos, and bill reminders.\n"
        "Replies are private to you unless noted."
    )
    e.add_field(
        name="Available now",
        value=(
            "`/carl help` this message\n"
            "`/carl settings` view household settings\n"
            "`/carl setup` (admins) set time zone, reminder channel and time\n"
            "`/carl status` (admins) health overview"
        ),
        inline=False,
    )
    e.add_field(
        name="Coming soon",
        value="`/grocery`, `/todo`, `/bill`",
        inline=False,
    )
    return e


def settings_embed(s: GuildSettings) -> discord.Embed:
    e = discord.Embed(title="Household settings", color=COLOR)
    channel = f"<#{s.reminder_channel_id}>" if s.reminder_channel_id else "Not set"
    summary = (
        "Off"
        if s.summary_frequency == "off"
        else (
            f"Daily at {s.summary_time}"
            if s.summary_frequency == "daily"
            else f"Weekly on {_SUMMARY_DAYS[s.summary_weekday]} at {s.summary_time}"
        )
    )
    e.add_field(name="Time zone", value=s.timezone)
    e.add_field(name="Reminder time", value=s.reminder_time)
    e.add_field(name="Reminder channel", value=channel)
    e.add_field(name="Currency", value=s.default_currency)
    e.add_field(
        name="Default bill reminders",
        value=", ".join(f"{d}d" if d else "due day" for d in s.default_bill_offsets),
    )
    e.add_field(name="Bill summary", value=summary)
    e.add_field(name="Date order", value="Month/Day" if s.date_order == "MDY" else "Day/Month")
    return e


def setup_result_embed(s: GuildSettings, changed: list[str]) -> discord.Embed:
    e = settings_embed(s)
    e.title = "Settings saved"
    e.set_footer(text="Updated: " + ", ".join(changed))
    return e
