"""Confirm / Cancel buttons for destructive actions.

Only the person who started the action can press them, within two minutes.
custom_id: carl:v1:cf:<action>:<target>:<user>:<expires_epoch>:<yes|no>
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

import discord

from carl.discord_ui import responses
from carl.discord_ui.components import ids
from carl.discord_ui.components.base import app_context, guard
from carl.discord_ui.responses import respond
from carl.domain.models import Actor

CONFIRM_TTL_SECONDS = 120
NOT_YOURS = "This confirmation belongs to someone else."
EXPIRED = "This confirmation expired. Run the command again."

# action name -> async handler(interaction, actor, target_id) -> text shown after confirming
ConfirmHandler = Callable[[discord.Interaction, Actor, int], Awaitable[str]]
# optional follow-up run after the user has been answered (e.g. refresh the live list)
AfterHandler = Callable[[discord.Interaction], Awaitable[None]]
CONFIRM_HANDLERS: dict[str, ConfirmHandler] = {}
CONFIRM_AFTER: dict[str, AfterHandler] = {}


def register_confirm_handler(
    action: str, handler: ConfirmHandler, after: AfterHandler | None = None
) -> None:
    CONFIRM_HANDLERS[action] = handler
    if after is not None:
        CONFIRM_AFTER[action] = after


def check_confirm(
    owner_id: int, presser_id: int, expires_epoch: int, now_epoch: float
) -> str | None:
    """None when the press is allowed, otherwise the reason it isn't."""
    if presser_id != owner_id:
        return NOT_YOURS
    if now_epoch > expires_epoch:
        return EXPIRED
    return None


class ConfirmButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=(
        r"carl:v1:cf:(?P<action>[a-z_]+):(?P<target>\d+):(?P<user>\d+):(?P<exp>\d+):"
        r"(?P<ans>yes|no)"
    ),
):
    def __init__(
        self,
        action: str,
        target_id: int,
        user_id: int,
        expires_epoch: int,
        answer: str,
        *,
        label: str,
        style: discord.ButtonStyle,
    ) -> None:
        self.action = action
        self.target_id = target_id
        self.user_id = user_id
        self.expires_epoch = expires_epoch
        self.answer = answer
        super().__init__(
            discord.ui.Button(
                label=label,
                style=style,
                custom_id=ids.build("cf", action, target_id, user_id, expires_epoch, answer),
            )
        )

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> ConfirmButton:
        return cls(
            match["action"],
            int(match["target"]),
            int(match["user"]),
            int(match["exp"]),
            match["ans"],
            label=item.label or "",
            style=item.style,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await guard(interaction, lambda actor: self._handle(interaction, actor))

    async def _handle(self, interaction: discord.Interaction, actor: Actor) -> None:
        now = app_context(interaction).clock.now().timestamp()
        problem = check_confirm(self.user_id, interaction.user.id, self.expires_epoch, now)
        if problem == EXPIRED:
            await interaction.response.edit_message(content=EXPIRED, embed=None, view=None)
            return
        if problem:
            await respond(interaction, problem)
            return
        if self.answer == "no":
            await interaction.response.edit_message(content="Cancelled.", embed=None, view=None)
            return
        handler = CONFIRM_HANDLERS.get(self.action)
        if handler is None:
            await respond(interaction, "That action is no longer available.")
            return
        text = await handler(interaction, actor, self.target_id)
        # The result is a short-lived confirmation: it deletes itself after a few seconds.
        await interaction.response.edit_message(
            content=None,
            embed=responses.summary_embed(text),
            view=None,
            delete_after=responses.BRIEF_SECONDS,
        )
        after = CONFIRM_AFTER.get(self.action)
        if after is not None:
            await after(interaction)


def build_confirm_view(
    action: str, target_id: int, user_id: int, now_epoch: float, *, yes_label: str
) -> discord.ui.View:
    """A View holding Confirm and Cancel buttons. Stopped immediately so discord.py doesn't keep
    it in memory (the persistent ConfirmButton handles clicks)."""
    expires = int(now_epoch) + CONFIRM_TTL_SECONDS
    view = discord.ui.View(timeout=None)
    view.add_item(
        ConfirmButton(
            action,
            target_id,
            user_id,
            expires,
            "yes",
            label=yes_label,
            style=discord.ButtonStyle.danger,
        )
    )
    view.add_item(
        ConfirmButton(
            action,
            target_id,
            user_id,
            expires,
            "no",
            label="Cancel",
            style=discord.ButtonStyle.secondary,
        )
    )
    view.stop()
    return view
