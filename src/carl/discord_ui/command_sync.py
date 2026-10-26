"""Sync guild commands only when the command definitions changed."""

from __future__ import annotations

import hashlib
import json
import logging

import discord
from discord import app_commands

from carl.repositories.app_state_repo import AppStateRepo

log = logging.getLogger("carl.sync")
STATE_KEY = "command_hash"


def command_hash(tree: app_commands.CommandTree, guild: discord.abc.Snowflake) -> str:
    payload = [cmd.to_dict(tree) for cmd in tree.get_commands(guild=guild)]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


async def sync_if_changed(
    tree: app_commands.CommandTree,
    guild: discord.abc.Snowflake,
    state: AppStateRepo,
    now: str,
) -> bool:
    """Sync the guild's commands if their hash differs from the stored one."""
    current = command_hash(tree, guild)
    if await state.get(STATE_KEY) == current:
        log.info("commands_unchanged")
        return False
    synced = await tree.sync(guild=guild)
    await state.set(STATE_KEY, current, now)
    log.info("commands_synced count=%d", len(synced))
    return True
