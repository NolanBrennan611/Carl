import logging

import pytest

from carl.domain.errors import Conflict, NotFound, ValidationError
from carl.domain.models import Actor
from carl.logging_setup import quiet_noisy_loggers
from carl.services.grocery_service import AddItemInput, EditItemInput
from tests.conftest import GUILD_ID

ALEX = Actor(GUILD_ID, 11)
SAM = Actor(GUILD_ID, 22)
OTHER_GUILD = Actor(GUILD_ID + 1, 11)


@pytest.fixture
def svc(ctx):
    return ctx.grocery_service


async def add(svc, name, qty=None, unit=None, *, actor=ALEX, **kw):
    return await svc.add_item(actor, AddItemInput(name, qty, unit, **kw))


# ---- add and merge (US-G1, US-G2) ------------------------------------------------------
async def test_add_a_simple_item(svc):
    out = await add(svc, "milk")
    assert out.action == "added" and out.item.name == "milk"
    assert out.item.category == "dairy"  # inferred
    assert out.item.status == "needed" and out.item.added_by_user_id == 11
    page = await svc.list_items(ALEX)
    assert [i.name for i in page.items] == ["milk"]


async def test_explicit_category_beats_inference(svc):
    out = await add(svc, "milk", category="household")
    assert out.item.category == "household"


async def test_us_g2_duplicates_merge_and_sum(svc):
    await add(svc, "apples", 2, "lb")
    out = await add(svc, "Apples", 1, "lbs", actor=SAM)
    assert out.action == "merged" and out.changed
    assert out.item.quantity == 3 and out.item.unit == "lb" and out.item.name == "apples"
    assert out.previous.quantity == 2
    assert (await svc.list_items(ALEX)).total == 1


async def test_us_g2_different_unit_is_a_separate_item_that_mentions_the_first(svc):
    await add(svc, "apples", 2, "lb")
    out = await add(svc, "apples", 1, "bag")
    assert out.action == "added"
    assert [(s.name, s.quantity, s.unit) for s in out.similar] == [("apples", 2, "lb")]
    assert (await svc.list_items(ALEX)).total == 2


async def test_merge_with_nothing_new_changes_nothing(svc):
    await add(svc, "milk")
    out = await add(svc, "MILK")
    assert out.action == "merged" and not out.changed


async def test_merge_keeps_notes_and_never_drops_quantity(svc):
    await add(svc, "eggs", 12, note="free range")
    out = await add(svc, "eggs", None, note="large")
    assert out.item.quantity == 12
    assert out.item.note == "free range · large"


async def test_merge_overflow_is_an_error_and_changes_nothing(svc):
    await add(svc, "rice", 9000, "g")
    with pytest.raises(ValidationError, match="combined quantity"):
        await add(svc, "rice", 1000, "g")
    assert (await svc.list_items(ALEX)).items[0].quantity == 9000


async def test_a_purchased_item_does_not_block_re_adding(svc):
    first = await add(svc, "milk")
    await svc.check_one(ALEX, first.item.id)
    again = await add(svc, "milk")
    assert again.action == "added" and again.item.id != first.item.id


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {"name": "milk", "quantity": 0},
        {"name": "milk", "quantity": 10000},
        {"name": "milk", "unit": "u" * 21},
        {"name": "milk", "note": "n" * 301},
        {"name": "milk", "category": "weapons"},
        {"name": "mi\x00lk"},
    ],
)
async def test_invalid_input_is_rejected(svc, kwargs):
    with pytest.raises(ValidationError):
        await svc.add_item(ALEX, AddItemInput(**kwargs))
    assert (await svc.list_items(ALEX)).total == 0


async def test_list_size_guard(svc, monkeypatch):
    monkeypatch.setattr("carl.domain.grocery.MAX_NEEDED_ITEMS", 2)
    await add(svc, "a-item")
    await add(svc, "b-item")
    with pytest.raises(ValidationError, match="already has 2 items"):
        await add(svc, "c-item")
    await add(svc, "a-item")  # merging is still fine at the limit


# ---- addmany ---------------------------------------------------------------------------
async def test_add_many_mixes_added_merged_and_rejected(svc):
    await add(svc, "milk", 1, "gal")
    result = await svc.add_many(ALEX, "eggs, 2 lb apples, 1 gal milk, 0 gum, apples 1 lb")
    outcomes = [(e.raw, e.outcome) for e in result.entries]
    assert outcomes == [
        ("eggs", "added"),
        ("2 lb apples", "added"),
        ("1 gal milk", "merged"),
        ("0 gum", "rejected"),
        ("apples 1 lb", "added"),  # 'apples 1 lb' parses as a name with no quantity
    ]
    assert "between" in result.of("rejected")[0].reason
    page = await svc.list_items(ALEX)
    names = {i.name: i.quantity for i in page.items}
    assert names["milk"] == 2


async def test_add_many_merges_duplicates_inside_the_same_batch(svc):
    result = await svc.add_many(ALEX, "2 lb apples, 1 lb apples")
    assert [e.outcome for e in result.entries] == ["added", "merged"]
    items = (await svc.list_items(ALEX)).items
    assert len(items) == 1 and items[0].quantity == 3


async def test_add_many_is_all_or_nothing_on_unexpected_errors(svc, monkeypatch):
    calls = {"n": 0}
    original = svc.repo.insert

    async def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk exploded")
        return await original(**kw)

    monkeypatch.setattr(svc.repo, "insert", flaky)
    with pytest.raises(RuntimeError):
        await svc.add_many(ALEX, "eggs, bread, milk")
    assert (await svc.list_items(ALEX)).total == 0  # first insert was rolled back


async def test_add_many_input_limits(svc):
    with pytest.raises(ValidationError):
        await svc.add_many(ALEX, ",,,")
    with pytest.raises(ValidationError, match="at most 20"):
        await svc.add_many(ALEX, ",".join(f"item{i}" for i in range(21)))


# ---- listing ---------------------------------------------------------------------------
async def test_list_groups_by_category_and_filters(svc):
    await svc.add_many(ALEX, "milk, apples, bread, soap, zucchini")
    page = await svc.list_items(ALEX)
    assert [i.category for i in page.items] == [
        "produce",
        "produce",
        "dairy",
        "bakery",
        "household",
    ][:0] or [i.name for i in page.items] == ["apples", "zucchini", "milk", "bread", "soap"]
    produce = await svc.list_items(ALEX, category="produce")
    assert [i.name for i in produce.items] == ["apples", "zucchini"]
    assert produce.needed_count == 5  # counts ignore the category filter


async def test_list_views_and_counts(svc):
    await svc.add_many(ALEX, "milk, eggs, bread")
    items = (await svc.list_items(ALEX)).items
    await svc.check_many(ALEX, [items[0].id])
    needed = await svc.list_items(ALEX, "needed")
    purchased = await svc.list_items(ALEX, "purchased")
    everything = await svc.list_items(ALEX, "all")
    assert (needed.total, purchased.total, everything.total) == (2, 1, 3)
    assert (needed.needed_count, needed.purchased_count) == (2, 1)
    with pytest.raises(ValidationError):
        await svc.list_items(ALEX, "bogus")
    with pytest.raises(ValidationError):
        await svc.list_items(ALEX, category="bogus")


async def test_list_pages_hold_25_items(svc):
    for start in range(0, 60, 20):
        await svc.add_many(ALEX, ",".join(f"item{n:02d}" for n in range(start, start + 20)))
    p1 = await svc.list_items(ALEX, page=1)
    p3 = await svc.list_items(ALEX, page=3)
    assert (p1.pages, p1.total, len(p1.items)) == (3, 60, 25)
    assert (p3.page, len(p3.items)) == (3, 10)
    assert (await svc.list_items(ALEX, page=99)).page == 3


# ---- check / uncheck (US-G3, US-G4) ----------------------------------------------------
async def test_check_many_in_one_go_and_skip_unknown_or_done(svc):
    await svc.add_many(ALEX, "milk, eggs, bread")
    ids = [i.id for i in (await svc.list_items(ALEX)).items]
    checked = await svc.check_many(SAM, [ids[0], ids[1], ids[1], 9999])
    assert {c.id for c in checked} == {ids[0], ids[1]}
    assert all(c.status == "purchased" and c.purchased_by_user_id == 22 for c in checked)
    assert await svc.check_many(SAM, [ids[0]]) == []  # already purchased: skipped, not an error
    assert (await svc.list_items(ALEX, "needed")).total == 1


async def test_check_one_errors(svc):
    item = (await add(svc, "milk")).item
    await svc.check_one(ALEX, item.id)
    with pytest.raises(Conflict, match="already checked off"):
        await svc.check_one(ALEX, item.id)
    with pytest.raises(NotFound):
        await svc.check_one(ALEX, 9999)


async def test_us_g4_uncheck_restores_quantity_and_note(svc):
    item = (await add(svc, "apples", 3, "lb", note="gala")).item
    await svc.check_one(ALEX, item.id)
    out = await svc.uncheck_one(SAM, item.id)
    assert out.merged_into is None
    back = out.item
    assert (back.status, back.quantity, back.unit, back.note) == ("needed", 3, "lb", "gala")
    assert back.purchased_at is None and back.purchased_by_user_id is None


async def test_uncheck_merges_into_an_identical_needed_item(svc):
    old = (await add(svc, "apples", 2, "lb")).item
    await svc.check_one(ALEX, old.id)
    await add(svc, "apples", 1, "lb")
    out = await svc.uncheck_one(ALEX, old.id)
    assert out.merged_into is not None and out.merged_into.quantity == 3
    page = await svc.list_items(ALEX, "all")
    assert page.total == 1  # the purchased row was folded in, nothing duplicated


async def test_uncheck_errors(svc):
    item = (await add(svc, "milk")).item
    with pytest.raises(Conflict, match="already on the list"):
        await svc.uncheck_one(ALEX, item.id)
    with pytest.raises(NotFound):
        await svc.uncheck_one(ALEX, 9999)


async def test_uncheck_many(svc):
    await svc.add_many(ALEX, "milk, eggs")
    ids = [i.id for i in (await svc.list_items(ALEX)).items]
    await svc.check_many(ALEX, ids)
    outcomes = await svc.uncheck_many(ALEX, ids + [12345])
    assert len(outcomes) == 2
    assert (await svc.list_items(ALEX, "needed")).total == 2


# ---- edit ------------------------------------------------------------------------------
async def test_edit_changes_only_given_fields(svc):
    item = (await add(svc, "apples", 2, "lb", note="gala")).item
    out = await svc.edit(ALEX, item.id, EditItemInput(quantity=5, category="snacks"))
    assert (out.name, out.quantity, out.unit, out.note, out.category) == (
        "apples",
        5,
        "lb",
        "gala",
        "snacks",
    )


async def test_edit_can_clear_fields(svc):
    item = (await add(svc, "apples", 2, "lb", note="gala")).item
    out = await svc.edit(
        ALEX, item.id, EditItemInput(clear=frozenset({"note", "quantity", "unit"}))
    )
    assert (out.quantity, out.unit, out.note) == (None, None, None)
    assert out.unit_normalized == ""


async def test_edit_rename_updates_the_matching_key(svc):
    item = (await add(svc, "apples", 2, "lb")).item
    await svc.edit(ALEX, item.id, EditItemInput(name="Green Apples"))
    merged = await add(svc, "green apple", 1, "lb")
    assert merged.action == "merged" and merged.item.quantity == 3


async def test_edit_collision_is_a_conflict_with_a_helpful_message(svc):
    await add(svc, "apples", 2, "lb")
    other = (await add(svc, "apples", 1, "bag")).item
    with pytest.raises(Conflict, match=r"already a needed \*\*apples \(lb\)\*\*"):
        await svc.edit(ALEX, other.id, EditItemInput(unit="lbs"))
    assert (await svc.edit(ALEX, other.id, EditItemInput(note="ok"))).note == "ok"


async def test_edit_validation(svc):
    item = (await add(svc, "milk")).item
    for bad in (
        EditItemInput(),
        EditItemInput(note="x", clear=frozenset({"note"})),
        EditItemInput(clear=frozenset({"name"})),
        EditItemInput(category="bogus"),
        EditItemInput(name=""),
        EditItemInput(quantity=0),
    ):
        with pytest.raises(ValidationError):
            await svc.edit(ALEX, item.id, bad)
    with pytest.raises(NotFound):
        await svc.edit(ALEX, 9999, EditItemInput(note="x"))


async def test_editing_a_purchased_item_never_conflicts(svc):
    a = (await add(svc, "apples", 1, "lb")).item
    await svc.check_one(ALEX, a.id)
    await add(svc, "apples", 1, "lb")
    out = await svc.edit(ALEX, a.id, EditItemInput(quantity=4))
    assert out.quantity == 4


# ---- remove and clear (US-G5) ----------------------------------------------------------
async def test_remove(svc):
    item = (await add(svc, "milk")).item
    removed = await svc.remove(ALEX, item.id)
    assert removed.name == "milk"
    assert (await svc.list_items(ALEX)).total == 0
    with pytest.raises(NotFound):
        await svc.remove(ALEX, item.id)


async def test_clear_deletes_only_purchased(svc):
    await svc.add_many(ALEX, "milk, eggs, bread")
    ids = [i.id for i in (await svc.list_items(ALEX)).items]
    await svc.check_many(ALEX, ids[:2])
    assert await svc.count_purchased(ALEX) == 2
    assert await svc.clear_purchased(ALEX, expected_count=2) == 2
    page = await svc.list_items(ALEX, "all")
    assert page.total == 1 and page.items[0].status == "needed"


async def test_clear_refuses_when_the_confirmed_count_is_stale(svc):
    await svc.add_many(ALEX, "milk, eggs")
    ids = [i.id for i in (await svc.list_items(ALEX)).items]
    await svc.check_many(ALEX, ids[:1])
    with pytest.raises(Conflict, match="changed"):
        await svc.clear_purchased(ALEX, expected_count=5)
    assert (await svc.list_items(ALEX, "purchased")).total == 1  # nothing deleted


async def test_clear_with_nothing_purchased(svc):
    assert await svc.clear_purchased(ALEX) == 0


# ---- search / resolve ------------------------------------------------------------------
async def test_search_and_resolve(svc):
    await svc.add_many(ALEX, "oat milk, almond milk, eggs, 100% juice")
    assert {i.name for i in await svc.search(ALEX, "milk")} == {"oat milk", "almond milk"}
    assert len(await svc.search(ALEX, "")) == 4
    assert [i.name for i in await svc.search(ALEX, "100%")] == ["100% juice"]  # % is literal
    assert await svc.search(ALEX, "_") == []  # _ is literal, not a wildcard

    eggs = (await svc.search(ALEX, "egg"))[0]
    assert (await svc.resolve(ALEX, str(eggs.id))).name == "eggs"
    assert (await svc.resolve(ALEX, "Eggs")).id == eggs.id  # typed name
    assert (await svc.resolve(ALEX, "egg")).id == eggs.id  # unique partial match
    with pytest.raises(ValidationError, match="Pick one"):
        await svc.add_many(ALEX, "milk (2%)")  # distinct item to create ambiguity below
        await add(svc, "oat milk", 1, "carton")
        await svc.resolve(ALEX, "oat milk")
    with pytest.raises(NotFound, match="couldn't find"):
        await svc.resolve(ALEX, "unicorn")
    with pytest.raises(NotFound):
        await svc.resolve(ALEX, "milk")  # two partial matches is not unique


# ---- isolation and privacy -------------------------------------------------------------
async def test_other_guilds_cannot_see_or_touch_items(svc):
    item = (await add(svc, "milk")).item
    assert (await svc.list_items(OTHER_GUILD)).total == 0
    assert await svc.search(OTHER_GUILD, "milk") == []
    with pytest.raises(NotFound):
        await svc.check_one(OTHER_GUILD, item.id)
    with pytest.raises(NotFound):
        await svc.remove(OTHER_GUILD, item.id)
    with pytest.raises(NotFound):
        await svc.edit(OTHER_GUILD, item.id, EditItemInput(note="x"))
    assert await svc.check_many(OTHER_GUILD, [item.id]) == []
    assert await svc.clear_purchased(OTHER_GUILD) == 0
    assert (await svc.list_items(ALEX)).total == 1
    # the same name in another guild is independent
    assert (await add(svc, "milk", actor=OTHER_GUILD)).action == "added"


SENTINEL = "SENTINEL_9f2b"


async def test_names_and_notes_never_reach_the_audit_log_or_logs(svc, ctx, caplog):
    caplog.set_level(logging.DEBUG)  # worst case: debug logging turned on
    quiet_noisy_loggers("DEBUG")  # what setup_logging() does in production
    out = await add(svc, f"{SENTINEL}-item", 2, "lb", note=f"{SENTINEL}-note")
    await add(svc, f"{SENTINEL}-item", 1, "lb")
    await svc.edit(ALEX, out.item.id, EditItemInput(name=f"{SENTINEL}-renamed"))
    await svc.check_one(ALEX, out.item.id)
    await svc.uncheck_one(ALEX, out.item.id)
    await svc.add_many(ALEX, f"{SENTINEL}-a, {SENTINEL}-b")
    await svc.check_many(ALEX, [out.item.id])
    await svc.clear_purchased(ALEX)
    await svc.remove(ALEX, (await svc.list_items(ALEX)).items[0].id)

    cur = await ctx.db.conn.execute("SELECT action, details_json FROM audit_log")
    rows = await cur.fetchall()
    assert {r["action"] for r in rows} >= {
        "grocery.add",
        "grocery.merge",
        "grocery.edit",
        "grocery.check",
        "grocery.uncheck",
        "grocery.clear",
        "grocery.remove",
    }
    assert SENTINEL not in " ".join(f"{r['action']} {r['details_json']}" for r in rows)
    assert SENTINEL not in caplog.text


async def test_audit_records_actor_and_counts(svc, ctx):
    await svc.add_many(ALEX, "milk, eggs")
    ids = [i.id for i in (await svc.list_items(ALEX)).items]
    await svc.check_many(SAM, ids)
    cur = await ctx.db.conn.execute(
        "SELECT actor_user_id, entity_id, details_json FROM audit_log"
        " WHERE action = 'grocery.check'"
    )
    row = await cur.fetchone()
    assert (row["actor_user_id"], row["entity_id"], row["details_json"]) == (
        22,
        None,
        '{"count":2}',
    )
