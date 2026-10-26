"""Money as integer minor units. Floats never touch money."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from carl.domain.errors import ValidationError

_EXPONENTS = {
    "USD": 2, "EUR": 2, "GBP": 2, "CAD": 2, "AUD": 2, "NZD": 2, "MXN": 2, "CHF": 2,
    "JPY": 0, "KRW": 0,
}  # fmt: skip
_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CAD": "$", "AUD": "$", "NZD": "$"}
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
MAX_MINOR = 100_000_000_000


def exponent(currency: str) -> int:
    return _EXPONENTS.get(currency, 2)


def normalize_currency(value: str) -> str:
    code = value.strip().upper()
    if not _CURRENCY_RE.match(code):
        raise ValidationError("Currency must be a 3-letter code like USD.")
    return code


def parse_amount(value: str | int | float | Decimal, currency: str) -> int:
    """Parse a user amount into minor units. Rejects excess precision (e.g. 1.234 USD)."""
    if isinstance(value, float):
        value = repr(value)
    text = str(value).strip().replace(",", "").lstrip("$€£¥")
    try:
        dec = Decimal(text)
    except InvalidOperation as exc:
        raise ValidationError("Amount must be a number like 84.20.") from exc
    if not dec.is_finite() or dec < 0:
        raise ValidationError("Amount must be zero or more.")
    scaled = dec * (10 ** exponent(currency))
    if scaled != scaled.to_integral_value():
        raise ValidationError(f"{currency} amounts can have at most {exponent(currency)} decimals.")
    minor = int(scaled)
    if minor > MAX_MINOR:
        raise ValidationError("Amount is too large.")
    return minor


def format_amount(minor: int, currency: str) -> str:
    exp = exponent(currency)
    sign = "-" if minor < 0 else ""
    minor = abs(minor)
    if exp == 0:
        number = f"{minor:,}"
    else:
        whole, frac = divmod(minor, 10**exp)
        number = f"{whole:,}.{frac:0{exp}d}"
    symbol = _SYMBOLS.get(currency)
    return f"{sign}{symbol}{number}" if symbol else f"{sign}{number} {currency}"
