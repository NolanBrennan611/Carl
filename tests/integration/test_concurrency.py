"""Overlapping commands (two people tapping at once) must queue up, not fail."""

import asyncio

import pytest

from carl.domain.models import Actor
from carl.services.grocery_service import AddItemInput
from tests.conftest import GUILD_ID

ALEX = Actor(GUILD_ID, 11)
SAM = Actor(GUILD_ID, 22)


async def test_overlapping_writes_wait_for_each_other(ctx):
    svc = ctx.grocery_service
    results = await asyncio.gather(
        *(svc.add_item(ALEX if i % 2 else SAM, AddItemInput(f"item {i}")) for i in range(12))
    )
    assert [r.action for r in results] == ["added"] * 12
    assert (await svc.list_items(ALEX)).total == 12


async def test_overlapping_merges_do_not_lose_quantity(ctx):
    svc = ctx.grocery_service
    await asyncio.gather(*(svc.add_item(ALEX, AddItemInput("rice", 1, "lb")) for _ in range(10)))
    (item,) = (await svc.list_items(ALEX)).items
    assert item.quantity == 10


async def test_a_failing_transaction_rolls_back_without_hurting_the_next(ctx):
    db = ctx.db

    async def failing():
        async with db.transaction():
            await db.conn.execute(
                "INSERT INTO app_state (key, value, updated_at) VALUES ('x', '1', 't')"
            )
            await asyncio.sleep(0.01)
            raise RuntimeError("boom")

    async def fine():
        await asyncio.sleep(0.001)
        async with db.transaction():
            await db.conn.execute(
                "INSERT INTO app_state (key, value, updated_at) VALUES ('y', '2', 't')"
            )

    results = await asyncio.gather(failing(), fine(), return_exceptions=True)
    assert isinstance(results[0], RuntimeError) and results[1] is None
    assert await ctx.app_state.get("x") is None  # rolled back
    assert await ctx.app_state.get("y") == "2"  # unaffected by the other's failure


async def test_nesting_in_the_same_task_is_still_an_error(ctx):
    async with ctx.db.transaction():
        with pytest.raises(RuntimeError, match="Nested"):
            async with ctx.db.transaction():
                pass
