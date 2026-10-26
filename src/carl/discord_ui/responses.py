"""Small helpers for replying to interactions."""

from __future__ import annotations

import discord

NO_MENTIONS = discord.AllowedMentions.none()
MAX_MESSAGE = 2000


def safe(text: str) -> str:
    """Escape markdown and mentions in user-typed text before placing it in a message."""
    return discord.utils.escape_markdown(discord.utils.escape_mentions(text))


def clip(text: str, limit: int = MAX_MESSAGE) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def respond(
    interaction: discord.Interaction, message: str, *, ephemeral: bool = True
) -> None:
    """Send a text reply whether or not the interaction was already answered."""
    message = clip(message)
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=ephemeral, allowed_mentions=NO_MENTIONS)
    else:
        await interaction.response.send_message(
            message, ephemeral=ephemeral, allowed_mentions=NO_MENTIONS
        )
