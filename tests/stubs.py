"""Stand-ins for discord.py interactions, enough to drive component callbacks offline."""

from __future__ import annotations

from types import SimpleNamespace

from tests.conftest import ADMIN_ROLE_ID, GUILD_ID, ROLE_ID


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


class StubFollowup:
    def __init__(self) -> None:
        self.sent: list[tuple[str | None, dict]] = []

    async def send(self, content=None, **kwargs) -> None:
        self.sent.append((content, kwargs))


def make_member(role_ids=(ROLE_ID,), user_id: int = 7, manage_guild: bool = False):
    return SimpleNamespace(
        id=user_id,
        roles=[SimpleNamespace(id=r) for r in role_ids],
        guild_permissions=SimpleNamespace(manage_guild=manage_guild),
    )


ADMIN_ROLES = (ROLE_ID, ADMIN_ROLE_ID)


def make_interaction(ctx, member=None, guild_id: int = GUILD_ID):
    return SimpleNamespace(
        guild_id=guild_id,
        user=member or make_member(),
        client=SimpleNamespace(ctx=ctx),
        extras={},
        response=StubResponse(),
        followup=StubFollowup(),
    )
