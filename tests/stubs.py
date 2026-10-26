"""Stand-ins for discord.py objects, enough to drive commands and component callbacks offline."""

from __future__ import annotations

from types import SimpleNamespace

import discord

from carl.discord_ui.live_list import LiveList
from tests.conftest import ADMIN_ROLE_ID, GUILD_ID, ROLE_ID


def http_error(kind: type[discord.HTTPException], status: int = 404) -> discord.HTTPException:
    """A discord.NotFound / Forbidden / HTTPException that needs no real HTTP response."""
    return kind(SimpleNamespace(status=status, reason="stub"), "stub error")


class FakePartialMessage:
    def __init__(self, fake: FakeDiscord, channel_id: int, message_id: int) -> None:
        self.fake, self.channel_id, self.message_id = fake, channel_id, message_id

    async def edit(self, **kwargs) -> None:
        if self.fake.edit_error is not None:
            raise self.fake.edit_error
        self.fake.edits.append(
            {"channel_id": self.channel_id, "message_id": self.message_id, **kwargs}
        )

    async def delete(self) -> None:
        if self.fake.delete_error is not None:
            raise self.fake.delete_error
        self.fake.deletes.append((self.channel_id, self.message_id))


class FakeDiscord:
    """Records what Carl does to messages it posted earlier."""

    def __init__(self) -> None:
        self.edits: list[dict] = []
        self.deletes: list[tuple[int, int]] = []
        self.edit_error: Exception | None = None
        self.delete_error: Exception | None = None
        self._next_id = 9000
        self._live: dict[int, LiveList] = {}

    def messageable_for(self, channel_id: int):
        return SimpleNamespace(
            get_partial_message=lambda message_id: FakePartialMessage(self, channel_id, message_id)
        )

    def next_message_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def live_list(self, ctx) -> LiveList:
        """One LiveList per context, shared by every interaction in a test."""
        if id(ctx) not in self._live:
            self._live[id(ctx)] = LiveList(ctx, self.messageable_for)
        return self._live[id(ctx)]


class StubResponse:
    def __init__(self) -> None:
        self.done = False
        self.sent: list[tuple[str | None, dict]] = []
        self.edits: list[dict] = []

    def is_done(self) -> bool:
        return self.done

    async def send_message(self, content=None, **kwargs) -> None:
        self.done = True
        self.sent.append((content, kwargs))

    async def edit_message(self, **kwargs) -> None:
        self.done = True
        self.edits.append(kwargs)


class StubSentMessage:
    def __init__(self, deletes: list[float | None]) -> None:
        self._deletes = deletes

    async def delete(self, *, delay: float | None = None) -> None:
        self._deletes.append(delay)


class StubFollowup:
    def __init__(self) -> None:
        self.sent: list[tuple[str | None, dict]] = []
        self.scheduled_deletes: list[float | None] = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
        return StubSentMessage(self.scheduled_deletes)


def make_member(role_ids=(ROLE_ID,), user_id: int = 7, manage_guild: bool = False):
    return SimpleNamespace(
        id=user_id,
        roles=[SimpleNamespace(id=r) for r in role_ids],
        guild_permissions=SimpleNamespace(manage_guild=manage_guild),
    )


ADMIN_ROLES = (ROLE_ID, ADMIN_ROLE_ID)


def make_interaction(
    ctx,
    member=None,
    guild_id: int = GUILD_ID,
    *,
    discord_fake: FakeDiscord | None = None,
    message_id: int | None = None,
    channel_id: int = 555,
):
    """`message_id` makes it a click on an existing message (a component interaction)."""
    fake = discord_fake or FakeDiscord()

    async def original_response():
        return SimpleNamespace(id=fake.next_message_id(), channel=SimpleNamespace(id=channel_id))

    return SimpleNamespace(
        guild_id=guild_id,
        user=member or make_member(),
        client=SimpleNamespace(ctx=ctx, live_list=fake.live_list(ctx)),
        extras={},
        message=SimpleNamespace(id=message_id) if message_id is not None else None,
        response=StubResponse(),
        followup=StubFollowup(),
        original_response=original_response,
    )
