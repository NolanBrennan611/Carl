"""Grocery rules: categories, units, merging duplicates, multi-item parsing.

Pure and deterministic (no AI, no I/O). See docs/requirements.md FR-G-*.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from carl.domain.errors import ValidationError
from carl.domain.models import GroceryItem

# --------------------------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------------------------
CATEGORIES = (
    "produce",
    "dairy",
    "meat_seafood",
    "bakery",
    "pantry",
    "frozen",
    "beverages",
    "snacks",
    "household",
    "personal_care",
    "other",
)

CATEGORY_LABELS: dict[str, tuple[str, str]] = {
    "produce": ("🥬", "Produce"),
    "dairy": ("🥛", "Dairy"),
    "meat_seafood": ("🥩", "Meat & seafood"),
    "bakery": ("🍞", "Bakery"),
    "pantry": ("🥫", "Pantry"),
    "frozen": ("🧊", "Frozen"),
    "beverages": ("🥤", "Beverages"),
    "snacks": ("🍿", "Snacks"),
    "household": ("🧻", "Household"),
    "personal_care": ("🧴", "Personal care"),
    "other": ("🛒", "Other"),
}

MIN_QUANTITY = 0.01
MAX_QUANTITY = 9999.0
MAX_ADDMANY = 20
MAX_NEEDED_ITEMS = 500
NOTE_JOINER = " · "
MAX_NAME = 100
MAX_UNIT = 20
MAX_NOTE = 300


def category_label(category: str) -> str:
    return CATEGORY_LABELS[category][1]


def sort_items(items: Iterable[GroceryItem]) -> list[GroceryItem]:
    """Category order, then needed before purchased, then name."""
    return sorted(
        items,
        key=lambda i: (
            CATEGORIES.index(i.category),
            0 if i.status == "needed" else 1,
            i.name_normalized,
            i.id,
        ),
    )


# Comma-separated keywords per category. Multi-word entries are matched as phrases first.
_KEYWORD_LISTS: dict[str, str] = {
    "produce": (
        "apple, banana, orange, lemon, lime, grape, strawberry, blueberry, raspberry, blackberry,"
        " cherry, peach, pear, plum, mango, pineapple, watermelon, melon, cantaloupe, kiwi,"
        " avocado, tomato, potato, sweet potato, onion, garlic, ginger, carrot, celery, cucumber,"
        " lettuce, spinach, kale, cabbage, broccoli, cauliflower, bell pepper, pepper, zucchini,"
        " squash, mushroom, corn, asparagus, beet, radish, eggplant, cilantro, parsley, basil,"
        " mint, herb, scallion, green onion, leek, grapefruit, tangerine, clementine, pumpkin,"
        " salad, arugula, brussels sprout, green bean, jalapeno, berry, fruit, vegetable, produce,"
        " dill, rosemary, thyme, shallot, turnip, cranberry, apricot, nectarine, pomegranate,"
        " coconut, fig, date, chive, bok choy, romaine, spring mix, sprout"
    ),
    "dairy": (
        "milk, cheese, butter, yogurt, yoghurt, cream, sour cream, cream cheese, cottage cheese,"
        " egg, half and half, creamer, mozzarella, cheddar, parmesan, feta, ricotta, kefir,"
        " whipped cream, almond milk, oat milk, soy milk, coconut milk, buttermilk, brie,"
        " swiss, provolone, gouda, string cheese, shredded cheese, margarine, ghee, custard"
    ),
    "meat_seafood": (
        "chicken, beef, pork, turkey, bacon, sausage, ham, steak, ground beef, ground turkey,"
        " salmon, shrimp, tuna, fish, cod, tilapia, lamb, hot dog, deli meat, salami, pepperoni,"
        " rib, roast, brisket, crab, lobster, scallop, meatball, chuck, sirloin, bratwurst,"
        " prosciutto, trout, halibut, mahi, clam, mussel, oyster, anchovy, sardine, jerky meat,"
        " drumstick, wing, thigh, breast, patty, burger, ground pork, kielbasa, chorizo"
    ),
    "bakery": (
        "bread, bagel, muffin, croissant, roll, bun, tortilla, pita, cake, donut, doughnut,"
        " baguette, cupcake, pie, naan, english muffin, hamburger bun, hot dog bun, sourdough,"
        " brioche, ciabatta, focaccia, pastry, danish, scone, flatbread, wrap, biscuit,"
        " cinnamon roll, dinner roll"
    ),
    "pantry": (
        "rice, pasta, noodle, spaghetti, macaroni, flour, sugar, salt, oil, olive oil, vinegar,"
        " sauce, ketchup, mustard, mayo, mayonnaise, cereal, oatmeal, oat, granola, bean, lentil,"
        " soup, broth, stock, canned tuna, canned tomato, peanut butter, jam, jelly, honey, syrup,"
        " spice, black pepper, baking soda, baking powder, yeast, vanilla, cocoa, chocolate chip,"
        " tomato sauce, tomato paste, salsa, breadcrumb, cornstarch, quinoa, couscous, taco shell,"
        " seasoning, soy sauce, hot sauce, bbq sauce, dressing, marinade, pickle, olive, relish,"
        " chickpea, tahini, hummus, almond butter, nutella, pancake mix, cake mix, chili powder,"
        " cumin, paprika, cinnamon, oregano, garlic powder, onion powder, bouillon, ramen"
    ),
    "frozen": (
        "ice cream, popsicle, pizza, fries, tater tot, waffle, frozen, ice, sorbet, gelato,"
        " pot pie, fish stick, chicken nugget, hash brown, edamame, dumpling, burrito"
    ),
    "beverages": (
        "water, juice, soda, cola, coffee, tea, beer, wine, lemonade, sparkling water, seltzer,"
        " kombucha, energy drink, sports drink, gatorade, orange juice, liquor, vodka, whiskey,"
        " coffee bean, pop, cider, tonic, club soda, coconut water, protein shake, drink mix,"
        " rum, gin, tequila, bourbon, champagne, cocktail"
    ),
    "snacks": (
        "chip, cracker, cookie, popcorn, pretzel, candy, chocolate, nut, almond, peanut, cashew,"
        " walnut, pistachio, trail mix, granola bar, jerky, gummy, fruit snack, protein bar,"
        " pudding, dried fruit, raisin, snack, brownie, marshmallow, cheez, goldfish, oreo,"
        " rice cake, seaweed snack, fruit leather, licorice"
    ),
    "household": (
        "paper towel, toilet paper, tissue, napkin, trash bag, garbage bag, dish soap, detergent,"
        " laundry, bleach, sponge, foil, aluminum foil, plastic wrap, ziploc, battery, light bulb,"
        " cleaner, dishwasher, air freshener, candle, wipe, mop, broom, glove, sandwich bag,"
        " freezer bag, parchment, wax paper, fabric softener, dryer sheet, windex, lysol,"
        " disinfectant, scrub, toilet cleaner, trash can liner, paper plate, plastic cup"
    ),
    "personal_care": (
        "shampoo, conditioner, soap, hand soap, body wash, toothpaste, toothbrush, deodorant,"
        " razor, lotion, sunscreen, floss, mouthwash, tampon, cotton swab, q-tip, makeup,"
        " lip balm, contact solution, vitamin, medicine, ibuprofen, tylenol, advil, band-aid,"
        " bandaid, diaper, baby wipe, shaving cream, perfume, cologne, nail polish, hair gel,"
        " face wash, moisturizer, cough drop, allergy, aspirin, sanitary pad"
    ),
}

_WORD_RE = re.compile(r"[a-z0-9'-]+")


def _forms(token: str) -> Iterator[str]:
    """Singular candidates for a token (berries -> berry, tomatoes -> tomato, apples -> apple)."""
    yield token
    if token.endswith("ies") and len(token) > 4:
        yield token[:-3] + "y"
    if token.endswith("es") and len(token) > 3:
        yield token[:-2]
    if token.endswith("s") and len(token) > 2:
        yield token[:-1]


def _build_keyword_tables() -> tuple[dict[str, str], list[tuple[tuple[str, ...], str]]]:
    words: dict[str, str] = {}
    phrases: list[tuple[tuple[str, ...], str]] = []
    for category, listing in _KEYWORD_LISTS.items():
        for raw in listing.split(","):
            entry = raw.strip()
            if not entry:
                continue
            parts = tuple(entry.split())
            if len(parts) == 1:
                words.setdefault(entry, category)
            else:
                phrases.append((parts, category))
    phrases.sort(key=lambda p: -len(p[0]))  # longest phrase wins
    return words, phrases


_WORDS, _PHRASES = _build_keyword_tables()
KEYWORD_COUNT = len(_WORDS) + len(_PHRASES)


def _phrase_matches(tokens: list[str], phrase: tuple[str, ...]) -> bool:
    n = len(phrase)
    for start in range(len(tokens) - n + 1):
        if all(phrase[k] in set(_forms(tokens[start + k])) for k in range(n)):
            return True
    return False


def infer_category(name: str) -> str:
    """Deterministic keyword lookup. Phrases first, then single words from the last word back
    (the head noun is usually last: 'chicken broth' -> broth). Unknown -> 'other'."""
    text = unicodedata.normalize("NFKC", name).casefold()
    tokens = _WORD_RE.findall(text)
    if not tokens:
        return "other"
    if "frozen" in tokens:
        return "frozen"
    for phrase, category in _PHRASES:
        if _phrase_matches(tokens, phrase):
            return category
    for token in reversed(tokens):
        for form in _forms(token):
            if form in _WORDS:
                return _WORDS[form]
    return "other"


# --------------------------------------------------------------------------------------------
# Units and quantities
# --------------------------------------------------------------------------------------------
_UNIT_GROUPS: dict[str, tuple[str, ...]] = {
    "lb": ("lb", "lbs", "pound", "pounds"),
    "oz": ("oz", "ounce", "ounces"),
    "kg": ("kg", "kgs", "kilogram", "kilograms", "kilo", "kilos"),
    "g": ("g", "gram", "grams", "gm"),
    "gal": ("gal", "gallon", "gallons"),
    "l": ("l", "liter", "liters", "litre", "litres", "ltr"),
    "ml": ("ml", "milliliter", "milliliters", "millilitre", "millilitres"),
    "qt": ("qt", "quart", "quarts"),
    "pt": ("pt", "pint", "pints"),
    "dozen": ("dozen", "doz", "dozens"),
    "pack": ("pack", "packs", "package", "packages", "pkg", "pkgs"),
    "bag": ("bag", "bags"),
    "box": ("box", "boxes"),
    "can": ("can", "cans", "tin", "tins"),
    "bottle": ("bottle", "bottles"),
    "bunch": ("bunch", "bunches"),
    "ct": ("ct", "count", "counts"),
    "carton": ("carton", "cartons"),
    "jar": ("jar", "jars"),
    "loaf": ("loaf", "loaves"),
    "pc": ("pc", "pcs", "piece", "pieces"),
    "slice": ("slice", "slices"),
    "roll": ("roll", "rolls"),
    "bar": ("bar", "bars"),
    "cup": ("cup", "cups"),
    "tbsp": ("tbsp", "tablespoon", "tablespoons"),
    "tsp": ("tsp", "teaspoon", "teaspoons"),
}
_UNIT_LOOKUP = {alias: canon for canon, aliases in _UNIT_GROUPS.items() for alias in aliases}
KNOWN_UNIT_WORDS = frozenset(_UNIT_LOOKUP)
COMMON_UNITS = tuple(_UNIT_GROUPS)  # for autocomplete


def normalize_unit(unit: str | None) -> str:
    """Matching key for a unit: '' when absent; synonyms collapse (lbs, pounds -> lb)."""
    if unit is None:
        return ""
    text = unicodedata.normalize("NFKC", unit).casefold().strip().rstrip(".")
    text = re.sub(r"\s+", " ", text)
    if not text:
        return ""
    if text in _UNIT_LOOKUP:
        return _UNIT_LOOKUP[text]
    if len(text) > 3 and text.endswith("s") and not text.endswith("ss"):
        return text[:-1]
    return text


def validate_quantity(quantity: float | None) -> float | None:
    if quantity is None:
        return None
    if not math.isfinite(quantity):
        raise ValidationError("Quantity must be a number.")
    rounded = round(float(quantity), 4)
    if rounded < MIN_QUANTITY or rounded > MAX_QUANTITY:
        raise ValidationError(f"Quantity must be between {MIN_QUANTITY:g} and {MAX_QUANTITY:g}.")
    return rounded


def format_quantity(quantity: float) -> str:
    """3.0 -> '3', 1.5 -> '1.5', 0.3333 -> '0.3333'."""
    return f"{quantity:.4f}".rstrip("0").rstrip(".")


def quantity_text(quantity: float | None, unit: str | None) -> str:
    """'3 lb', '2 cartons', '12', 'bag' (unit only), or ''."""
    parts = []
    if quantity is not None:
        parts.append(format_quantity(quantity))
    if unit:
        parts.append(unit)
    return " ".join(parts)


# --------------------------------------------------------------------------------------------
# Merging duplicates (FR-G-04)
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MergeFields:
    quantity: float | None
    unit: str | None
    note: str | None
    category: str


def merge(existing: MergeFields, incoming: MergeFields) -> MergeFields:
    """Combine an incoming add with the needed item that has the same name and unit.

    - Quantities are summed when both exist; a missing quantity never erases an existing one.
    - Different notes are appended with ' · ' (nothing is silently dropped).
    - The existing category wins, except 'other' is upgraded to a real category.
    """
    if existing.quantity is not None and incoming.quantity is not None:
        total = round(existing.quantity + incoming.quantity, 4)
        if total > MAX_QUANTITY:
            raise ValidationError(f"The combined quantity would be over {MAX_QUANTITY:g}.")
        quantity: float | None = total
    else:
        quantity = existing.quantity if existing.quantity is not None else incoming.quantity

    note = existing.note
    if incoming.note:
        if not existing.note:
            note = incoming.note
        else:
            have = {part.casefold() for part in existing.note.split(NOTE_JOINER)}
            if incoming.note.casefold() not in have:
                note = f"{existing.note}{NOTE_JOINER}{incoming.note}"
        if note is not None and len(note) > MAX_NOTE:
            raise ValidationError(
                f"The combined note would be over {MAX_NOTE} characters. Shorten the note."
            )

    category = existing.category
    if existing.category == "other" and incoming.category != "other":
        category = incoming.category

    return MergeFields(
        quantity=quantity,
        unit=existing.unit or incoming.unit,
        note=note,
        category=category,
    )


# --------------------------------------------------------------------------------------------
# /grocery addmany parsing
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ParsedEntry:
    raw: str
    name: str | None = None
    quantity: float | None = None
    unit: str | None = None
    error: str | None = None


_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)?)x?$")
_FRACTION_RE = re.compile(r"^(\d+)/(\d+)$")


def _parse_number(token: str) -> float | None:
    match = _NUMBER_RE.match(token.casefold())
    if match:
        return float(match.group(1))
    frac = _FRACTION_RE.match(token)
    if frac and int(frac.group(2)) != 0:
        return int(frac.group(1)) / int(frac.group(2))
    return None


def parse_entry(raw: str) -> ParsedEntry:
    """'[qty] [unit] [of] name' -> ParsedEntry. A unit word is only a unit when a name follows."""
    tokens = raw.split()
    if not tokens:
        return ParsedEntry(raw=raw, error="Empty entry.")
    quantity: float | None = None
    unit: str | None = None
    i = 0
    number = _parse_number(tokens[0])
    if number is not None:
        i = 1
        try:
            quantity = validate_quantity(number)
        except ValidationError as exc:
            return ParsedEntry(raw=raw, error=exc.message)
        if i < len(tokens) - 1 and tokens[i].casefold().rstrip(".") in KNOWN_UNIT_WORDS:
            unit = tokens[i].rstrip(".")
            i += 1
            if tokens[i].casefold() == "of" and i < len(tokens) - 1:
                i += 1
    name = " ".join(tokens[i:])
    if not name:
        return ParsedEntry(raw=raw, error="There's no item name.")
    return ParsedEntry(raw=raw, name=name, quantity=quantity, unit=unit)


def parse_addmany(text: str) -> list[ParsedEntry]:
    parts = [p.strip() for p in re.split(r"[,\n]", text)]
    parts = [p for p in parts if p]
    if not parts:
        raise ValidationError("Type at least one item. Separate items with commas.")
    if len(parts) > MAX_ADDMANY:
        raise ValidationError(f"Add at most {MAX_ADDMANY} items at once.")
    return [parse_entry(p) for p in parts]
