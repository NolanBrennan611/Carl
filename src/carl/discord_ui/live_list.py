"""The one "live" grocery list message.

`/grocery list` posted publicly becomes the live list: Carl remembers its channel and message
ID and edits that message in place whenever the list changes, so people only need to post it
once. Posting a new one deletes the old one, so there is never more than one.

Everything here is best effort. A missing or uneditable message is forgotten with a warning;
it never makes a user's command fail. Callers update the live list *after* answering the user,
so Discord's 3-second response limit is never at risk.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import discord

from carl.discord_ui.components.grocery import render_list
from carl.discord_ui.responses import NO_MENTIONS
from carl.domain import timeutil
from carl.domain.models import Actor

if TYPE_CHECKING:
    from carl.app import AppContext

log = logging.getLogger("carl.live_list")

STATE_KEY = "grocery_live_list"


@dataclass(frozen=True)
class LiveRef:
    channel_id: int
    message_id: int
    view: str = "needed"  # what the message shows; kept when it is refreshed
    category: str | None = None


class LiveList:
    def __init__(self, ctx: AppContext, messageable_for: Callable[[int], Any]) -> None:
        """`messageable_for(channel_id)` returns something with get_partial_message(id)
        (CarlBot passes `get_partial_messageable`)."""
        self.ctx = ctx
        self._messageable_for = messageable_for
        self._lock = asyncio.Lock()  # edits happen one at a time, so the last one is the newest

    # ---- stored reference
    async def current(self) -> LiveRef | None:
        raw = await self.ctx.app_state.get(STATE_KEY)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return LiveRef(
                channel_id=int(data["channel_id"]),
                message_id=int(data["message_id"]),
                view=data.get("view", "needed"),
                category=data.get("category"),
            )
        except (ValueError, KeyError, TypeError):
            log.warning("live_list_state_unreadable; forgetting it")
            await self._write("")
            return None

    async def _write(self, value: str) -> None:
        now = timeutil.to_db_instant(timeutil.utc_now(self.ctx.clock))
        # Through the transaction queue so it can't tangle with another command's writes.
        async with self.ctx.db.transaction():
            await self.ctx.app_state.set(STATE_KEY, value, now)

    async def remember(self, ref: LiveRef) -> None:
        await self._write(
            json.dumps(
                {
                    "channel_id": ref.channel_id,
                    "message_id": ref.message_id,
                    "view": ref.view,
                    "category": ref.category,
                },
                separators=(",", ":"),
            )
        )

    async def forget(self) -> None:
        await self._write("")

    def _partial(self, ref: LiveRef) -> Any:
        return self._messageable_for(ref.channel_id).get_partial_message(ref.message_id)

    # ---- replace / refresh
    async def replace(
        self, channel_id: int, message_id: int, *, view: str = "needed", category: str | None = None
    ) -> None:
        """Make this message the live list and delete the previous one."""
        async with self._lock:
            old = await self.current()
            if old is not None and old.message_id != message_id:
                try:
                    await self._partial(old).delete()
                except discord.HTTPException:
                    log.info("old_live_list_already_gone")
            await self.remember(LiveRef(channel_id, message_id, view, category))

    async def refresh(self, guild_id: int, *, skip_message_id: int | None = None) -> bool:
        """Re-render the live message. True if it was edited."""
        async with self._lock:
            ref = await self.current()
            if ref is None or ref.message_id == skip_message_id:
                return False
            embed, view = await render_list(self.ctx, Actor(guild_id, 0), ref.view, ref.category, 1)
            try:
                await self._partial(ref).edit(embed=embed, view=view, allowed_mentions=NO_MENTIONS)
            except (discord.NotFound, discord.Forbidden) as exc:
                log.warning("live_list_lost reason=%s; forgetting it", type(exc).__name__)
                await self.forget()
                return False
            except discord.HTTPException as exc:
                log.warning("live_list_edit_failed status=%s", exc.status)
                return False
            return True

    async def refresh_after(self, interaction: discord.Interaction) -> None:
        """Call after answering a user. Never raises. If the click came from the live message
        itself, that message was already updated by the click, so it is skipped."""
        message = getattr(interaction, "message", None)
        try:
            await self.refresh(
                interaction.guild_id,  # type: ignore[arg-type]
                skip_message_id=getattr(message, "id", None),
            )
        except Exception:  # noqa: BLE001 - background update must never hurt the user's command
            log.exception("live_list_refresh_failed")
