"""Reply text and list rendering for the grocery list. Pure functions (no I/O)."""

from __future__ import annotations

import discord

from carl.discord_ui.responses import clip, safe
from carl.domain.grocery import CATEGORIES, CATEGORY_LABELS, category_label, quantity_text
from carl.domain.models import GroceryItem
from carl.services.grocery_service import (
    AddManyResult,
    AddOutcome,
    GroceryPage,
    UncheckOutcome,
)

EMBED_LIMIT = 4000  # Discord allows 4096; leave headroom
NOTE_PREVIEW = 80


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def item_summary(item: GroceryItem) -> str:
    """'**apples** — 3 lb' (name in bold, quantity and unit when present)."""
    qty = quantity_text(item.quantity, item.unit)
    return f"**{safe(item.name)}**" + (f" — {safe(qty)}" if qty else "")


def plain_summary(item: GroceryItem) -> str:
    """'apples 3 lb' without bold, for compact lists."""
    qty = quantity_text(item.quantity, item.unit)
    return safe(item.name) + (f" {safe(qty)}" if qty else "")


# ---- command replies --------------------------------------------------------------------------
def add_reply(out: AddOutcome) -> str:
    item = out.item
    if out.action == "added":
        text = f"Added {item_summary(item)} ({category_label(item.category)})."
        if out.similar:
            others = ", ".join(plain_summary(s) for s in out.similar)
            text += f"\nAlso on the list: {others}"
        return text
    if not out.changed:
        return f"**{safe(item.name)}** is already on the list."
    qty = quantity_text(item.quantity, item.unit)
    detail = f": now {safe(qty)}" if qty else " (note updated)"
    return f"Merged with existing **{safe(item.name)}**{detail}."


def addmany_reply(result: AddManyResult) -> str:
    lines: list[str] = []
    added = result.of("added")
    merged = result.of("merged")
    rejected = result.of("rejected")
    if added:
        parts = [
            f"{plain_summary(e.item)} ({category_label(e.item.category)})" for e in added if e.item
        ]
        lines.append(f"Added {len(added)}: " + ", ".join(parts) + ".")
    if merged:
        parts = []
        for e in merged:
            assert e.item is not None
            qty = quantity_text(e.item.quantity, e.item.unit)
            parts.append(f"{safe(e.item.name)} → now {safe(qty)}" if qty else safe(e.item.name))
        lines.append(f"Merged {len(merged)}: " + ", ".join(parts) + ".")
    if rejected:
        parts = [f"“{safe(e.raw)}” ({safe(e.reason or 'invalid')})" for e in rejected]
        lines.append(f"Couldn't add {len(rejected)}: " + "; ".join(parts))
    return clip("\n".join(lines))


def check_reply(items: list[GroceryItem]) -> str:
    if len(items) == 1:
        return f"Checked off {item_summary(items[0])}."
    return f"Checked off {len(items)} items."


def uncheck_reply(out: UncheckOutcome) -> str:
    if out.merged_into is not None:
        qty = quantity_text(out.merged_into.quantity, out.merged_into.unit)
        detail = f": now {safe(qty)}" if qty else ""
        return (
            f"Put **{safe(out.item.name)}** back. Merged with the one already on the list{detail}."
        )
    return f"Put {item_summary(out.item)} back on the list."


def edit_reply(item: GroceryItem) -> str:
    extras = [category_label(item.category)]
    if item.note:
        extras.append(f"note: {safe(_truncate(item.note, NOTE_PREVIEW))}")
    return f"Updated {item_summary(item)} ({'; '.join(extras)})."


def remove_reply(item: GroceryItem) -> str:
    return f"Removed **{safe(item.name)}**."


# ---- list rendering -----------------------------------------------------------------------------
def list_title(page: GroceryPage) -> str:
    if page.view == "needed":
        title = f"🛒 Grocery list — {page.needed_count} needed"
    elif page.view == "purchased":
        title = f"✅ Purchased — {page.purchased_count} items"
    else:
        title = f"🛒 Grocery list — {page.needed_count} needed · {page.purchased_count} purchased"
    if page.category:
        title += f" · {category_label(page.category)}"
    return title


def _item_line(item: GroceryItem, view: str, include_note: bool, max_name: int) -> str:
    name = safe(_truncate(item.name, max_name))
    qty = quantity_text(item.quantity, item.unit)
    text = f"• {name}" + (f" — {safe(qty)}" if qty else "")
    if include_note and item.note:
        text += f" · note: {safe(_truncate(item.note, NOTE_PREVIEW))}"
    if view == "all" and item.status == "purchased":
        text = f"✔ ~~{text[2:]}~~"
    if view == "all":
        text += f" — added by <@{item.added_by_user_id}>"
    return text


def _build_lines(items: list[GroceryItem], view: str, include_note: bool, max_name: int) -> str:
    lines: list[str] = []
    current: str | None = None
    for item in items:
        if item.category != current:
            current = item.category
            emoji, label = CATEGORY_LABELS[current]
            if lines:
                lines.append("")
            lines.append(f"**{emoji} {label}**")
        lines.append(_item_line(item, view, include_note, max_name))
    return "\n".join(lines)


def list_description(page: GroceryPage) -> str:
    """Category-grouped lines that always fit in an embed, even for 25 very long items."""
    if not page.items:
        if page.view == "purchased":
            return "Nothing has been checked off yet."
        if page.category:
            return "Nothing in this category. Add items with `/grocery add`."
        return "The list is empty. Add items with `/grocery add` or `/grocery addmany`."
    text = ""
    for include_note, max_name in ((True, 100), (False, 100), (False, 60), (False, 40)):
        text = _build_lines(page.items, page.view, include_note, max_name)
        if len(text) <= EMBED_LIMIT:
            return text
    return text[: EMBED_LIMIT - 2].rstrip() + "\n…"


def list_embed(page: GroceryPage, updated_text: str) -> discord.Embed:
    embed = discord.Embed(
        title=list_title(page), description=list_description(page), color=discord.Color.green()
    )
    embed.set_footer(text=f"Page {page.page}/{page.pages} · Updated {updated_text}")
    return embed


def select_options(page: GroceryPage, mode: str) -> list[discord.SelectOption]:
    """Options for the multi-select: needed items to check off, or purchased to put back."""
    wanted = "needed" if mode == "check" else "purchased"
    options = []
    for item in page.items:
        if item.status != wanted:
            continue
        qty = quantity_text(item.quantity, item.unit)
        description = " · ".join(p for p in (category_label(item.category), qty) if p)
        options.append(
            discord.SelectOption(
                label=_truncate(item.name, 100) or "item",
                value=str(item.id),
                description=_truncate(description, 100) or None,
            )
        )
    return options[:25]


def category_choices() -> list[tuple[str, str]]:
    """(label, value) for the category option, in list order."""
    return [(f"{CATEGORY_LABELS[c][0]} {CATEGORY_LABELS[c][1]}", c) for c in CATEGORIES]
