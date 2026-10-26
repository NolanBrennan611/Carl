"""Shared plumbing for persistent components.

discord.py runs a DynamicItem callback for any matching custom_id, even after a restart, but it
does not call our error handling and does not run the command tree's access check. So every
callback goes through `guard`, which re-checks that the clicker is a household Member and turns
errors into friendly ephemeral replies.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import discord

from carl.discord_ui import errors
from carl.discord_ui.auth import resolve_actor
from carl.discord_ui.responses import respond
from carl.domain.errors import CarlError
from carl.domain.models import Actor

if TYPE_CHECKING:
    from carl.app import AppContext

log = logging.getLogger("carl.components")


def app_context(interaction: discord.Interaction) -> AppContext:
    return interaction.client.ctx  # type: ignore[attr-defined]


def actor_for(interaction: discord.Interaction) -> Actor:
    """Raises Forbidden unless the user is a household Member of the home guild."""
    return resolve_actor(interaction.guild_id, interaction.user, app_context(interaction).settings)


def autocomplete_actor(interaction: discord.Interaction) -> Actor | None:
    """Autocomplete bypasses the command tree's access check, so check here. None = no access."""
    try:
        return actor_for(interaction)
    except CarlError:
        return None


async def guard(
    interaction: discord.Interaction, handler: Callable[[Actor], Awaitable[None]]
) -> None:
    try:
        actor = actor_for(interaction)
        interaction.extras["actor"] = actor
        await handler(actor)
    except Exception as exc:  # noqa: BLE001 - everything becomes a reply
        try:
            await respond(interaction, errors.message_for(exc))
        except discord.HTTPException:
            log.warning("could_not_send_component_error_reply")
