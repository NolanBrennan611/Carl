from datetime import date

import pytest

from carl.domain import bills, formatting, money
from carl.domain.dates import add_months, parse_date
from carl.domain.errors import ValidationError
from carl.domain.text import clean_text, normalize_name

TODAY = date(2026, 10, 28)  # a Wednesday


# ---- dates (docs/discord-commands.md section 7) ---------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("today", date(2026, 10, 28)),
        ("Tomorrow", date(2026, 10, 29)),
        ("  TODAY ", date(2026, 10, 28)),
        ("fri", date(2026, 10, 30)),
        ("friday", date(2026, 10, 30)),
        ("wed", date(2026, 11, 4)),  # never today
        ("mon", date(2026, 11, 2)),
        ("next week", date(2026, 11, 2)),  # next Monday
        ("+3d", date(2026, 10, 31)),
        ("+2w", date(2026, 11, 11)),
        ("+1m", date(2026, 11, 28)),
        ("in 3 days", date(2026, 10, 31)),
        ("in 1 week", date(2026, 11, 4)),
        ("in 2 months", date(2026, 12, 28)),
        ("2026-11-05", date(2026, 11, 5)),
        ("11/5", date(2026, 11, 5)),
        ("11/5/2026", date(2026, 11, 5)),
        ("11/5/26", date(2026, 11, 5)),
        ("10/28", date(2026, 10, 28)),  # today counts
        ("10/27", date(2027, 10, 27)),  # already passed -> next year
        ("Nov 5", date(2026, 11, 5)),
        ("nov 5 2027", date(2027, 11, 5)),
        ("5 Nov", date(2026, 11, 5)),
        ("November 5, 2026", date(2026, 11, 5)),
        ("Sept 9", date(2027, 9, 9)),
    ],
)
def test_parse_date_mdy(text, expected):
    assert parse_date(text, TODAY) == expected


def test_parse_date_dmy_order():
    assert parse_date("11/5", TODAY, "DMY") == date(2027, 5, 11)
    assert parse_date("5/11/2026", TODAY, "DMY") == date(2026, 11, 5)


def test_month_end_relative_clamps():
    assert parse_date("+1m", date(2027, 1, 31)) == date(2027, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_feb_29_without_year_finds_next_leap_year():
    assert parse_date("2/29", date(2026, 3, 1)) == date(2028, 2, 29)


@pytest.mark.parametrize(
    "text", ["", "   ", "someday", "13/45", "2026-02-30", "2/30", "nov 40", "32 nov", "0/5", "+x"]
)
def test_parse_date_rejects_garbage(text):
    with pytest.raises(ValidationError) as exc:
        parse_date(text, TODAY)
    assert "11/5" in exc.value.message or "10 years" in exc.value.message


def test_parse_date_limits_to_ten_years():
    with pytest.raises(ValidationError, match="10 years"):
        parse_date("2040-01-01", TODAY)
    assert parse_date("2030-01-01", TODAY) == date(2030, 1, 1)


# ---- money -----------------------------------------------------------------------------------
def test_parse_amount_exact_decimal_math():
    assert money.parse_amount("84.20", "USD") == 8420
    assert money.parse_amount("$1,234.5", "USD") == 123450
    assert money.parse_amount(19.99, "USD") == 1999
    with pytest.raises(ValidationError):  # float noise is rejected, never silently rounded
        money.parse_amount(0.1 + 0.2, "USD")
    assert money.parse_amount(500, "JPY") == 500
    assert money.parse_amount("0", "USD") == 0


@pytest.mark.parametrize(
    ("value", "currency"),
    [("1.234", "USD"), ("12.5", "JPY"), ("-3", "USD"), ("abc", "USD"), ("nan", "USD"),
     ("inf", "USD"), ("9999999999999", "USD")],
)  # fmt: skip
def test_parse_amount_rejects(value, currency):
    with pytest.raises(ValidationError):
        money.parse_amount(value, currency)


def test_format_amount():
    assert money.format_amount(8420, "USD") == "$84.20"
    assert money.format_amount(5, "USD") == "$0.05"
    assert money.format_amount(123456789, "USD") == "$1,234,567.89"
    assert money.format_amount(500, "JPY") == "¥500"
    assert money.format_amount(1000, "CHF") == "10.00 CHF"
    assert money.format_amount(-250, "USD") == "-$2.50"


def test_normalize_currency():
    assert money.normalize_currency(" usd ") == "USD"
    with pytest.raises(ValidationError):
        money.normalize_currency("US")


# ---- text normalization ------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Apples ", "apple"),
        ("  OAT   MILK ", "oat milk"),
        ("Tomatoes", "tomatoe"),
        ("ＡＰＰＬＥ", "apple"),  # full-width forms fold via NFKC
        ("Electric", "electric"),
    ],
)
def test_normalize_name(a, b):
    assert normalize_name(a) == b


def test_normalize_name_keeps_short_and_double_s_words():
    assert normalize_name("glass") == "glass"
    assert normalize_name("bus") == "bus"
    assert normalize_name("gas") == "gas"
    assert normalize_name("") == ""
    assert normalize_name("Apples") == normalize_name("apple") == normalize_name("APPLES  ")


def test_clean_text_rules():
    assert clean_text("  hi  ", field="Name", max_len=10) == "hi"
    with pytest.raises(ValidationError, match="empty"):
        clean_text("   ", field="Name", max_len=10)
    with pytest.raises(ValidationError, match="at most 5"):
        clean_text("toolong", field="Name", max_len=5)
    with pytest.raises(ValidationError, match="aren't allowed"):
        clean_text("a\x00b", field="Name", max_len=10)
    with pytest.raises(ValidationError):
        clean_text("a\nb", field="Name", max_len=10)
    assert clean_text("a\nb", field="Notes", max_len=10, allow_newlines=True) == "a\nb"
    assert clean_text("", field="Notes", max_len=10, required=False) == ""


# ---- formatting ---------------------------------------------------------------------------------
def test_format_date():
    assert formatting.format_date(date(2026, 11, 1)) == "Sun, Nov 1, 2026"
    assert formatting.format_date_short(date(2026, 11, 1)) == "Sun Nov 1"


def test_relative_days():
    today = date(2026, 10, 28)
    assert formatting.relative_days(today, today) == "today"
    assert formatting.relative_days(date(2026, 10, 29), today) == "tomorrow"
    assert formatting.relative_days(date(2026, 10, 31), today) == "in 3 days"
    assert formatting.relative_days(date(2026, 10, 27), today) == "yesterday"
    assert formatting.relative_days(date(2026, 10, 22), today) == "6 days overdue"


# ---- bill offsets --------------------------------------------------------------------------------
def test_parse_offsets():
    assert bills.parse_offsets("3,0") == (3, 0)
    assert bills.parse_offsets(" 0 , 7 ,3 ") == (7, 3, 0)
    assert bills.parse_offsets("3,3,0") == (3, 0)
    assert bills.parse_offsets("60") == (60,)


@pytest.mark.parametrize("bad", ["", "a", "61", "1,2,3,4,5,6", "-1", "3;0", "1.5"])
def test_parse_offsets_rejects(bad):
    with pytest.raises(ValidationError):
        bills.parse_offsets(bad)
