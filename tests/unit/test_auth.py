from types import SimpleNamespace

import pytest

from carl.discord_ui.auth import ADMIN_ONLY, NO_ACCESS, require_admin, resolve_actor
from carl.domain.errors import Forbidden
from carl.domain.models import Actor
from tests.conftest import ADMIN_ROLE_ID, GUILD_ID, ROLE_ID


def member(role_ids=(), manage_guild=False, user_id=42):
    return SimpleNamespace(
        id=user_id,
        roles=[SimpleNamespace(id=r) for r in role_ids],
        guild_permissions=SimpleNamespace(manage_guild=manage_guild),
    )


def test_household_member_is_allowed(settings):
    actor = resolve_actor(GUILD_ID, member([ROLE_ID]), settings)
    assert actor == Actor(guild_id=GUILD_ID, user_id=42, is_admin=False)


def test_admin_by_role(settings):
    assert resolve_actor(GUILD_ID, member([ROLE_ID, ADMIN_ROLE_ID]), settings).is_admin


def test_admin_by_manage_server_permission(settings):
    assert resolve_actor(GUILD_ID, member([ROLE_ID], manage_guild=True), settings).is_admin


def test_admin_role_alone_without_household_role_is_denied(settings):
    with pytest.raises(Forbidden, match="don't have access"):
        resolve_actor(GUILD_ID, member([ADMIN_ROLE_ID]), settings)


def test_member_without_household_role_is_denied(settings):
    with pytest.raises(Forbidden) as exc:
        resolve_actor(GUILD_ID, member([999]), settings)
    assert exc.value.message == NO_ACCESS


def test_manage_server_without_household_role_is_denied(settings):
    with pytest.raises(Forbidden):
        resolve_actor(GUILD_ID, member([], manage_guild=True), settings)


def test_wrong_guild_is_denied(settings):
    with pytest.raises(Forbidden):
        resolve_actor(GUILD_ID + 1, member([ROLE_ID]), settings)


def test_direct_message_without_guild_is_denied(settings):
    with pytest.raises(Forbidden):
        resolve_actor(None, member([ROLE_ID]), settings)


def test_plain_user_without_roles_is_denied(settings):
    with pytest.raises(Forbidden):
        resolve_actor(GUILD_ID, SimpleNamespace(id=1), settings)  # discord.User has no roles


def test_admin_role_is_optional(settings, tmp_path):
    from dataclasses import replace

    no_admin_role = replace(settings, admin_role_id=None)
    assert not resolve_actor(GUILD_ID, member([ROLE_ID, ADMIN_ROLE_ID]), no_admin_role).is_admin
    assert resolve_actor(GUILD_ID, member([ROLE_ID], True), no_admin_role).is_admin


def test_require_admin():
    assert require_admin(Actor(1, 2, True)).user_id == 2
    with pytest.raises(Forbidden) as exc:
        require_admin(Actor(1, 2, False))
    assert exc.value.message == ADMIN_ONLY
