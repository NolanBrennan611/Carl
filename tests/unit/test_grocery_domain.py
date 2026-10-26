import pytest

from carl.domain import grocery as g
from carl.domain.errors import ValidationError
from carl.domain.models import GroceryItem
from carl.domain.paging import paginate


# ---- categories ------------------------------------------------------------------------------
def test_there_are_at_least_150_category_keywords():
    assert g.KEYWORD_COUNT >= 150


def test_all_keyword_categories_are_valid():
    assert set(g._KEYWORD_LISTS) <= set(g.CATEGORIES)
    assert set(g.CATEGORY_LABELS) == set(g.CATEGORIES)
    assert g.CATEGORIES[-1] == "other"


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("apples", "produce"),
        ("Strawberries", "produce"),
        ("tomatoes", "produce"),
        ("baby spinach", "produce"),
        ("milk", "dairy"),
        ("2% milk", "dairy"),
        ("oat milk", "dairy"),
        ("cream cheese", "dairy"),
        ("eggs", "dairy"),
        ("chicken breast", "meat_seafood"),
        ("ground beef", "meat_seafood"),
        ("tuna steaks", "meat_seafood"),
        ("canned tuna", "pantry"),
        ("hot dogs", "meat_seafood"),
        ("hot dog buns", "bakery"),
        ("sourdough bread", "bakery"),
        ("peanut butter", "pantry"),
        ("chicken broth", "pantry"),
        ("olive oil", "pantry"),
        ("black pepper", "pantry"),
        ("bell peppers", "produce"),
        ("ice cream", "frozen"),
        ("frozen peas", "frozen"),
        ("frozen chicken", "frozen"),
        ("orange juice", "beverages"),
        ("sparkling water", "beverages"),
        ("coffee", "beverages"),
        ("tortilla chips", "snacks"),
        ("paper towels", "household"),
        ("toilet paper", "household"),
        ("dish soap", "household"),
        ("hand soap", "personal_care"),
        ("toothpaste", "personal_care"),
        ("something unheard of", "other"),
        ("", "other"),
        ("!!!", "other"),
    ],
)
def test_infer_category(name, category):
    assert g.infer_category(name) == category


def test_sort_items_orders_by_category_then_status_then_name():
    def item(i, name, cat, status="needed"):
        return GroceryItem(
            i, 1, name, name, None, None, "", cat, None, status, 1, None, None, "t", "t"
        )

    ordered = g.sort_items(
        [
            item(1, "soap", "household"),
            item(2, "zucchini", "produce"),
            item(3, "apple", "produce", "purchased"),
            item(4, "banana", "produce"),
            item(5, "milk", "dairy"),
        ]
    )
    assert [i.name for i in ordered] == ["banana", "zucchini", "apple", "milk", "soap"]


# ---- units and quantities -----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "key"),
    [
        (None, ""),
        ("", ""),
        ("  ", ""),
        ("lb", "lb"),
        ("LBS", "lb"),
        ("pounds", "lb"),
        ("Lb.", "lb"),
        ("gallons", "gal"),
        ("cartons", "carton"),
        ("carton", "carton"),
        ("bunches", "bunch"),
        ("loaves", "loaf"),
        ("doz", "dozen"),
        ("cans", "can"),
        ("widgets", "widget"),  # unknown units fall back to a simple singular
        ("glass", "glass"),
    ],
)
def test_normalize_unit(raw, key):
    assert g.normalize_unit(raw) == key


def test_validate_quantity():
    assert g.validate_quantity(None) is None
    assert g.validate_quantity(2) == 2
    assert g.validate_quantity(0.333333) == 0.3333
    assert g.validate_quantity(9999) == 9999
    for bad in (0, 0.001, -1, 10000):
        with pytest.raises(ValidationError, match="between"):
            g.validate_quantity(bad)
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValidationError, match="must be a number"):
            g.validate_quantity(bad)


def test_format_quantity_and_text():
    assert g.format_quantity(3.0) == "3"
    assert g.format_quantity(1.5) == "1.5"
    assert g.format_quantity(0.3333) == "0.3333"
    assert g.quantity_text(3, "lb") == "3 lb"
    assert g.quantity_text(None, "bag") == "bag"
    assert g.quantity_text(12, None) == "12"
    assert g.quantity_text(None, None) == ""


# ---- merge matrix (FR-G-04) ---------------------------------------------------------------------
def F(q=None, unit=None, note=None, cat="produce"):
    return g.MergeFields(q, unit, note, cat)


def test_merge_numbers_are_summed():
    assert g.merge(F(2, "lb"), F(1, "lbs")).quantity == 3
    assert g.merge(F(0.1), F(0.2)).quantity == 0.3  # no float drift


def test_merge_missing_quantity_never_erases_existing():
    assert g.merge(F(2, "lb"), F(None)).quantity == 2
    assert g.merge(F(None), F(2, "lb")).quantity == 2
    assert g.merge(F(None), F(None)).quantity is None


def test_merge_keeps_existing_unit_text():
    assert g.merge(F(2, "lb"), F(1, "pounds")).unit == "lb"
    assert g.merge(F(None, None), F(1, "lb")).unit == "lb"


def test_merge_notes_are_appended_not_dropped():
    assert g.merge(F(note=None), F(note="organic")).note == "organic"
    assert g.merge(F(note="organic"), F(note=None)).note == "organic"
    assert g.merge(F(note="organic"), F(note="gala")).note == "organic · gala"
    assert g.merge(F(note="organic · gala"), F(note="GALA")).note == "organic · gala"
    assert g.merge(F(note="organic"), F(note="Organic")).note == "organic"


def test_merge_category_rules():
    assert g.merge(F(cat="produce"), F(cat="pantry")).category == "produce"
    assert g.merge(F(cat="other"), F(cat="pantry")).category == "pantry"
    assert g.merge(F(cat="pantry"), F(cat="other")).category == "pantry"


def test_merge_limits_are_enforced_not_silently_clamped():
    with pytest.raises(ValidationError, match="combined quantity"):
        g.merge(F(9000), F(1000))
    with pytest.raises(ValidationError, match="combined note"):
        g.merge(F(note="a" * 200), F(note="b" * 200))


# ---- addmany parsing -----------------------------------------------------------------------------
def entries(text):
    return [(e.name, e.quantity, e.unit) for e in g.parse_addmany(text)]


def test_parse_examples_from_the_spec():
    assert entries("milk, 2 lb apples, eggs") == [
        ("milk", None, None),
        ("apples", 2.0, "lb"),
        ("eggs", None, None),
    ]
    assert entries("3 cans tomatoes") == [("tomatoes", 3.0, "cans")]
    assert entries("1.5 kg flour") == [("flour", 1.5, "kg")]
    assert entries("2 apples") == [("apples", 2.0, None)]
    assert entries("12 eggs") == [("eggs", 12.0, None)]
    assert entries("1/2 gallon milk") == [("milk", 0.5, "gallon")]
    assert entries("2x bananas") == [("bananas", 2.0, None)]
    assert entries("2 lb of apples") == [("apples", 2.0, "lb")]
    assert entries("1 dozen eggs") == [("eggs", 1.0, "dozen")]


def test_a_unit_word_is_only_a_unit_when_a_name_follows():
    assert entries("2 can") == [("can", 2.0, None)]
    assert entries("3 bag") == [("bag", 3.0, None)]


def test_parse_splits_on_commas_and_newlines_and_skips_blanks():
    assert [e.name for e in g.parse_addmany("milk,\n\n eggs ,, bread\nbutter")] == [
        "milk",
        "eggs",
        "bread",
        "butter",
    ]


def test_parse_reports_bad_entries_without_failing_the_rest():
    parsed = g.parse_addmany("0 gum, milk, 10000 rice, 5")
    assert parsed[0].error and "between" in parsed[0].error
    assert parsed[1].name == "milk" and parsed[1].error is None
    assert parsed[2].error
    assert parsed[3].error and "no item name" in parsed[3].error.lower()


def test_parse_limits():
    with pytest.raises(ValidationError, match="at least one"):
        g.parse_addmany(" , \n ")
    assert len(g.parse_addmany(",".join(f"item{i}" for i in range(20)))) == 20
    with pytest.raises(ValidationError, match="at most 20"):
        g.parse_addmany(",".join(f"item{i}" for i in range(21)))


# ---- paging --------------------------------------------------------------------------------------
def test_paginate():
    w = paginate(60, 2, 25)
    assert (w.page, w.pages, w.start, w.end) == (2, 3, 25, 50)
    assert paginate(60, 99, 25).page == 3  # clamped high
    assert paginate(60, 0, 25).page == 1  # clamped low
    last = paginate(51, 3, 25)
    assert (last.start, last.end) == (50, 51)
    empty = paginate(0, 5, 25)
    assert (empty.page, empty.pages, empty.start, empty.end) == (1, 1, 0, 0)
    with pytest.raises(ValueError):
        paginate(5, 1, 0)
