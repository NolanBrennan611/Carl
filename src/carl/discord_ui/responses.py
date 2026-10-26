"""Small helpers for replying to interactions."""

from __future__ import annotations

import discord

NO_MENTIONS = discord.AllowedMentions.none()
MAX_MESSAGE = 2000
MAX_EMBED_TEXT = 4000

# How long a success confirmation stays visible before it deletes itself. Must stay well
# under Discord's 15-minute interaction limit. Error replies are never auto-deleted.
BRIEF_SECONDS = 10.0


def safe(text: str) -> str:
    """Escape markdown and mentions in user-typed text before placing it in a message."""
    return discord.utils.escape_markdown(discord.utils.escape_mentions(text))


def clip(text: str, limit: int = MAX_MESSAGE) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def summary_embed(text: str) -> discord.Embed:
    """A small embed holding a short confirmation."""
    return discord.Embed(description=clip(text, MAX_EMBED_TEXT), color=discord.Color.green())


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


async def respond_brief(
    interaction: discord.Interaction, text: str, *, delay: float | None = None
) -> None:
    """A private confirmation embed that deletes itself after `delay` seconds."""
    delay = BRIEF_SECONDS if delay is None else delay
    embed = summary_embed(text)
    if interaction.response.is_done():
        sent = await interaction.followup.send(
            embed=embed, ephemeral=True, allowed_mentions=NO_MENTIONS, wait=True
        )
        await sent.delete(delay=delay)  # schedules the delete in the background
    else:
        await interaction.response.send_message(
            embed=embed, ephemeral=True, allowed_mentions=NO_MENTIONS, delete_after=delay
        )
