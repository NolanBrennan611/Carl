"""Shared grocery list use cases (FR-G-01..11).

Every public method takes the Actor, runs its writes in one transaction, and records an audit
entry that holds IDs and counts only (never item names or notes).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from carl.clock import Clock
from carl.db.connection import Database
from carl.domain import grocery as rules
from carl.domain import timeutil
from carl.domain.errors import CarlError, Conflict, NotFound, ValidationError
from carl.domain.models import Actor, GroceryItem
from carl.domain.paging import paginate
from carl.domain.text import clean_text, normalize_name
from carl.repositories.audit_repo import AuditRepo
from carl.repositories.grocery_repo import GroceryRepo

PAGE_SIZE = 25
VIEWS = ("needed", "purchased", "all")


# ---- inputs and results ---------------------------------------------------------------------
@dataclass(frozen=True)
class AddItemInput:
    name: str
    quantity: float | None = None
    unit: str | None = None
    category: str | None = None  # None -> inferred from the name
    note: str | None = None


@dataclass(frozen=True)
class EditItemInput:
    name: str | None = None
    quantity: float | None = None
    unit: str | None = None
    category: str | None = None
    note: str | None = None
    clear: frozenset[str] = frozenset()  # subset of {"note", "quantity", "unit"}


@dataclass(frozen=True)
class AddOutcome:
    action: str  # 'added' | 'merged'
    item: GroceryItem
    previous: GroceryItem | None = None  # the item before a merge
    similar: list[GroceryItem] = field(default_factory=list)  # same name, other unit

    @property
    def changed(self) -> bool:
        """False when a merge changed nothing (e.g. adding 'milk' when 'milk' is listed)."""
        if self.action == "added" or self.previous is None:
            return True
        p, i = self.previous, self.item
        return (p.quantity, p.unit, p.note, p.category) != (i.quantity, i.unit, i.note, i.category)


@dataclass(frozen=True)
class AddManyEntry:
    raw: str
    outcome: str  # 'added' | 'merged' | 'rejected'
    item: GroceryItem | None = None
    reason: str | None = None


@dataclass(frozen=True)
class AddManyResult:
    entries: list[AddManyEntry]

    def of(self, outcome: str) -> list[AddManyEntry]:
        return [e for e in self.entries if e.outcome == outcome]


@dataclass(frozen=True)
class GroceryPage:
    items: list[GroceryItem]
    page: int
    pages: int
    total: int  # items matching the view/category filter
    needed_count: int  # whole list, ignoring filters
    purchased_count: int
    view: str
    category: str | None


@dataclass(frozen=True)
class UncheckOutcome:
    item: GroceryItem
    merged_into: GroceryItem | None = None


@dataclass(frozen=True)
class _Prepared:
    name: str
    name_normalized: str
    quantity: float | None
    unit: str | None
    unit_normalized: str
    category: str
    note: str | None


def _prepare(data: AddItemInput) -> _Prepared:
    name = clean_text(data.name, field="Item name", max_len=rules.MAX_NAME)
    unit = clean_text(data.unit or "", field="Unit", max_len=rules.MAX_UNIT, required=False)
    note = clean_text(data.note or "", field="Note", max_len=rules.MAX_NOTE, required=False)
    if data.category is not None and data.category not in rules.CATEGORIES:
        raise ValidationError("Unknown category.")
    return _Prepared(
        name=name,
        name_normalized=normalize_name(name),
        quantity=rules.validate_quantity(data.quantity),
        unit=unit or None,
        unit_normalized=rules.normalize_unit(unit),
        category=data.category or rules.infer_category(name),
        note=note or None,
    )


def _label(item: GroceryItem) -> str:
    return item.name + (f" ({item.unit})" if item.unit else "")


class GroceryService:
    def __init__(self, db: Database, clock: Clock, repo: GroceryRepo, audit: AuditRepo) -> None:
        self.db = db
        self.clock = clock
        self.repo = repo
        self.audit = audit

    def _now(self) -> str:
        return timeutil.to_db_instant(timeutil.utc_now(self.clock))

    async def _audit(
        self, actor: Actor, action: str, entity_id: int | None, details: dict | None = None
    ) -> None:
        await self.audit.add(
            guild_id=actor.guild_id,
            actor_user_id=actor.user_id,
            action=action,
            entity_type="grocery_item",
            entity_id=entity_id,
            details=details,
            at=self._now(),
        )

    async def _require(self, actor: Actor, item_id: int) -> GroceryItem:
        item = await self.repo.get(actor.guild_id, item_id)
        if item is None:
            raise NotFound("That item wasn't found. It may have been removed.")
        return item

    # ---- add ---------------------------------------------------------------------------------
    async def _add_prepared(self, actor: Actor, p: _Prepared) -> AddOutcome:
        """Insert or merge. Runs inside a transaction; raises before writing on any error."""
        now = self._now()
        existing = await self.repo.find_needed_by_key(
            actor.guild_id, p.name_normalized, p.unit_normalized
        )
        if existing is not None:
            merged = rules.merge(
                rules.MergeFields(
                    existing.quantity, existing.unit, existing.note, existing.category
                ),
                rules.MergeFields(p.quantity, p.unit, p.note, p.category),
            )
            await self.repo.update_content(
                guild_id=actor.guild_id,
                item_id=existing.id,
                name=existing.name,
                name_normalized=existing.name_normalized,
                quantity=merged.quantity,
                unit=merged.unit,
                unit_normalized=existing.unit_normalized,
                category=merged.category,
                note=merged.note,
                now=now,
            )
            await self._audit(actor, "grocery.merge", existing.id)
            item = await self._require(actor, existing.id)
            return AddOutcome("merged", item, previous=existing)

        needed, _ = await self.repo.counts(actor.guild_id)
        if needed >= rules.MAX_NEEDED_ITEMS:
            raise ValidationError(
                f"The list already has {rules.MAX_NEEDED_ITEMS} items. "
                "Check some off or remove them first."
            )
        new_id = await self.repo.insert(
            guild_id=actor.guild_id,
            name=p.name,
            name_normalized=p.name_normalized,
            quantity=p.quantity,
            unit=p.unit,
            unit_normalized=p.unit_normalized,
            category=p.category,
            note=p.note,
            added_by_user_id=actor.user_id,
            now=now,
        )
        await self._audit(actor, "grocery.add", new_id)
        similar = [
            i
            for i in await self.repo.find_needed_by_name(actor.guild_id, p.name_normalized)
            if i.id != new_id
        ]
        return AddOutcome("added", await self._require(actor, new_id), similar=similar)

    async def add_item(self, actor: Actor, data: AddItemInput) -> AddOutcome:
        prepared = _prepare(data)
        async with self.db.transaction():
            return await self._add_prepared(actor, prepared)

    async def add_many(self, actor: Actor, text: str) -> AddManyResult:
        """Parse 'milk, 2 lb apples, 3 cans tomatoes' and add every valid entry in one
        transaction. Entries that fail validation are reported, not fatal."""
        parsed = rules.parse_addmany(text)
        entries: list[AddManyEntry] = []
        async with self.db.transaction():
            for entry in parsed:
                if entry.error or entry.name is None:
                    entries.append(AddManyEntry(entry.raw, "rejected", reason=entry.error))
                    continue
                try:
                    prepared = _prepare(
                        AddItemInput(entry.name, entry.quantity, entry.unit, None, None)
                    )
                    outcome = await self._add_prepared(actor, prepared)
                except CarlError as exc:
                    entries.append(AddManyEntry(entry.raw, "rejected", reason=exc.message))
                    continue
                entries.append(AddManyEntry(entry.raw, outcome.action, item=outcome.item))
        return AddManyResult(entries)

    # ---- read --------------------------------------------------------------------------------
    async def list_items(
        self,
        actor: Actor,
        view: str = "needed",
        category: str | None = None,
        page: int = 1,
    ) -> GroceryPage:
        if view not in VIEWS:
            raise ValidationError("View must be needed, purchased, or all.")
        if category is not None and category not in rules.CATEGORIES:
            raise ValidationError("Unknown category.")
        status = None if view == "all" else view
        items = rules.sort_items(
            await self.repo.list_for_guild(actor.guild_id, status=status, category=category)
        )
        window = paginate(len(items), page, PAGE_SIZE)
        needed, purchased = await self.repo.counts(actor.guild_id)
        return GroceryPage(
            items=items[window.start : window.end],
            page=window.page,
            pages=window.pages,
            total=len(items),
            needed_count=needed,
            purchased_count=purchased,
            view=view,
            category=category,
        )

    async def search(
        self, actor: Actor, text: str, view: str = "all", limit: int = 25
    ) -> list[GroceryItem]:
        """For autocomplete: items whose name contains the text."""
        status = None if view == "all" else view
        return await self.repo.search(actor.guild_id, text.strip(), status, limit)

    async def resolve(self, actor: Actor, value: str, view: str = "all") -> GroceryItem:
        """Turn an autocomplete value (an ID) or typed text (a name) into one item."""
        value = value.strip()
        if value.isdigit():
            item = await self.repo.get(actor.guild_id, int(value))
            if item is not None:
                return item
        key = normalize_name(value)
        # Prefer the requested view. If nothing matches there, look at the whole list so the
        # caller can say something precise ("already on the list") instead of "not found".
        for status in dict.fromkeys([None if view == "all" else view, None]):
            exact = await self.repo.find_by_name(actor.guild_id, key, status) if key else []
            if len(exact) == 1:
                return exact[0]
            if len(exact) > 1:
                raise ValidationError(
                    f"There's more than one **{exact[0].name}** on the list. "
                    "Pick one from the suggestions."
                )
            partial = await self.repo.search(actor.guild_id, value, status, 2) if value else []
            if len(partial) == 1:
                return partial[0]
        raise NotFound(f"I couldn't find **{value}** on the list. Pick one of the suggestions.")

    # ---- check / uncheck ---------------------------------------------------------------------
    async def check_many(self, actor: Actor, item_ids: list[int]) -> list[GroceryItem]:
        """Mark needed items purchased. Missing or already-purchased IDs are skipped."""
        now = self._now()
        checked: list[GroceryItem] = []
        async with self.db.transaction():
            for item_id in dict.fromkeys(item_ids):
                if await self.repo.mark_purchased(actor.guild_id, item_id, actor.user_id, now):
                    item = await self.repo.get(actor.guild_id, item_id)
                    if item is not None:
                        checked.append(item)
            if checked:
                await self._audit(
                    actor,
                    "grocery.check",
                    checked[0].id if len(checked) == 1 else None,
                    {"count": len(checked)},
                )
        return checked

    async def check_one(self, actor: Actor, item_id: int) -> GroceryItem:
        item = await self._require(actor, item_id)
        if item.status == "purchased":
            raise Conflict(f"**{item.name}** is already checked off.")
        checked = await self.check_many(actor, [item_id])
        if not checked:
            raise Conflict(f"**{item.name}** is already checked off.")
        return checked[0]

    async def _uncheck_in_tx(self, actor: Actor, item: GroceryItem, now: str) -> UncheckOutcome:
        needed_twin = await self.repo.find_needed_by_key(
            actor.guild_id, item.name_normalized, item.unit_normalized
        )
        if needed_twin is None:
            await self.repo.mark_needed(actor.guild_id, item.id, now)
            return UncheckOutcome(await self._require(actor, item.id))
        merged = rules.merge(
            rules.MergeFields(
                needed_twin.quantity, needed_twin.unit, needed_twin.note, needed_twin.category
            ),
            rules.MergeFields(item.quantity, item.unit, item.note, item.category),
        )
        await self.repo.update_content(
            guild_id=actor.guild_id,
            item_id=needed_twin.id,
            name=needed_twin.name,
            name_normalized=needed_twin.name_normalized,
            quantity=merged.quantity,
            unit=merged.unit,
            unit_normalized=needed_twin.unit_normalized,
            category=merged.category,
            note=merged.note,
            now=now,
        )
        await self.repo.delete(actor.guild_id, item.id)
        return UncheckOutcome(item, merged_into=await self._require(actor, needed_twin.id))

    async def uncheck_many(self, actor: Actor, item_ids: list[int]) -> list[UncheckOutcome]:
        """Return purchased items to the list, merging into an identical needed item."""
        now = self._now()
        outcomes: list[UncheckOutcome] = []
        async with self.db.transaction():
            for item_id in dict.fromkeys(item_ids):
                item = await self.repo.get(actor.guild_id, item_id)
                if item is None or item.status != "purchased":
                    continue
                outcomes.append(await self._uncheck_in_tx(actor, item, now))
            if outcomes:
                await self._audit(
                    actor,
                    "grocery.uncheck",
                    outcomes[0].item.id if len(outcomes) == 1 else None,
                    {"count": len(outcomes), "merged": sum(1 for o in outcomes if o.merged_into)},
                )
        return outcomes

    async def uncheck_one(self, actor: Actor, item_id: int) -> UncheckOutcome:
        item = await self._require(actor, item_id)
        if item.status != "purchased":
            raise Conflict(f"**{item.name}** is already on the list.")
        outcomes = await self.uncheck_many(actor, [item_id])
        if not outcomes:
            raise Conflict(f"**{item.name}** is already on the list.")
        return outcomes[0]

    # ---- edit / remove / clear ---------------------------------------------------------------
    async def edit(self, actor: Actor, item_id: int, data: EditItemInput) -> GroceryItem:
        bad = set(data.clear) - {"note", "quantity", "unit"}
        if bad:
            raise ValidationError("You can only clear the note, quantity, or unit.")
        if (
            ("note" in data.clear and data.note is not None)
            or ("quantity" in data.clear and data.quantity is not None)
            or ("unit" in data.clear and data.unit is not None)
        ):
            raise ValidationError("You can't set and clear the same field.")
        if data.category is not None and data.category not in rules.CATEGORIES:
            raise ValidationError("Unknown category.")
        provided = [
            data.name,
            data.quantity,
            data.unit,
            data.category,
            data.note,
        ]
        if all(v is None for v in provided) and not data.clear:
            raise ValidationError("Nothing to change. Provide at least one option.")

        async with self.db.transaction():
            item = await self._require(actor, item_id)
            name = item.name
            if data.name is not None:
                name = clean_text(data.name, field="Item name", max_len=rules.MAX_NAME)
            quantity = item.quantity
            if "quantity" in data.clear:
                quantity = None
            elif data.quantity is not None:
                quantity = rules.validate_quantity(data.quantity)
            unit = item.unit
            if "unit" in data.clear:
                unit = None
            elif data.unit is not None:
                unit = (
                    clean_text(data.unit, field="Unit", max_len=rules.MAX_UNIT, required=False)
                    or None
                )
            note = item.note
            if "note" in data.clear:
                note = None
            elif data.note is not None:
                note = (
                    clean_text(data.note, field="Note", max_len=rules.MAX_NOTE, required=False)
                    or None
                )
            category = data.category or item.category

            name_norm = normalize_name(name)
            unit_norm = rules.normalize_unit(unit)
            key_changed = (name_norm, unit_norm) != (item.name_normalized, item.unit_normalized)
            if item.status == "needed" and key_changed:
                clash = await self.repo.find_needed_by_key(actor.guild_id, name_norm, unit_norm)
                if clash is not None and clash.id != item.id:
                    raise Conflict(
                        f"There's already a needed **{_label(clash)}**. "
                        "Remove one or change the unit."
                    )
            await self.repo.update_content(
                guild_id=actor.guild_id,
                item_id=item.id,
                name=name,
                name_normalized=name_norm,
                quantity=quantity,
                unit=unit,
                unit_normalized=unit_norm,
                category=category,
                note=note,
                now=self._now(),
            )
            fields = [
                label
                for label, given in (
                    ("name", data.name),
                    ("quantity", data.quantity),
                    ("unit", data.unit),
                    ("category", data.category),
                    ("note", data.note),
                )
                if given is not None
            ] + [f"clear_{c}" for c in sorted(data.clear)]
            await self._audit(actor, "grocery.edit", item.id, {"fields": fields})
            return await self._require(actor, item.id)

    async def remove(self, actor: Actor, item_id: int) -> GroceryItem:
        async with self.db.transaction():
            item = await self._require(actor, item_id)
            await self.repo.delete(actor.guild_id, item_id)
            await self._audit(actor, "grocery.remove", item_id)
        return item

    async def count_purchased(self, actor: Actor) -> int:
        _, purchased = await self.repo.counts(actor.guild_id)
        return purchased

    async def clear_purchased(self, actor: Actor, expected_count: int | None = None) -> int:
        """Delete all purchased items. With `expected_count` (the number the user confirmed),
        refuses if the list changed in the meantime."""
        async with self.db.transaction():
            _, purchased = await self.repo.counts(actor.guild_id)
            if expected_count is not None and purchased != expected_count:
                raise Conflict("The purchased list changed. Run `/grocery clear` again.")
            if purchased == 0:
                return 0
            deleted = await self.repo.delete_purchased(actor.guild_id)
            await self._audit(actor, "grocery.clear", None, {"count": deleted})
        return deleted
