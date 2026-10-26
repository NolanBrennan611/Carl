"""Authorization (docs/discord-commands.md section 3).

Works on duck-typed members so it can be unit-tested without Discord. A member needs:
`.id`, `.roles` (objects with `.id`), and `.guild_permissions.manage_guild`.
"""

from __future__ import annotations

from typing import Any

from carl.config import Settings
from carl.domain.errors import Forbidden
from carl.domain.models import Actor

NO_ACCESS = "You don't have access to Carl. Ask an admin for the household role."
ADMIN_ONLY = "Only Carl admins can do that."


def resolve_actor(guild_id: int | None, user: Any, settings: Settings) -> Actor:
    """Return the Actor for a Member, or raise Forbidden for everyone else.

    Outsiders are: interactions from other guilds or DMs, users who aren't guild Members
    (no roles), and members without the household role.
    """
    if guild_id is None or guild_id != settings.guild_id:
        raise Forbidden(NO_ACCESS)
    roles = getattr(user, "roles", None)
    if roles is None:
        raise Forbidden(NO_ACCESS)
    role_ids = {role.id for role in roles}
    if settings.household_role_id not in role_ids:
        raise Forbidden(NO_ACCESS)
    perms = getattr(user, "guild_permissions", None)
    is_admin = bool(
        (settings.admin_role_id is not None and settings.admin_role_id in role_ids)
        or (perms is not None and perms.manage_guild)
    )
    return Actor(guild_id=guild_id, user_id=user.id, is_admin=is_admin)


def require_admin(actor: Actor) -> Actor:
    if not actor.is_admin:
        raise Forbidden(ADMIN_ONLY)
    return actor
