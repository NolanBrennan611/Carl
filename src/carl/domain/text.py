"""Text cleaning and name normalization."""

from __future__ import annotations

import re
import unicodedata

from carl.domain.errors import ValidationError

_WS = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Key used only for matching (duplicates/merges); display names keep user text.

    NFKC -> casefold -> trim -> collapse whitespace -> strip a trailing 's' from the last
    word when that word is longer than 3 chars and doesn't end in 'ss'.
    """
    text = unicodedata.normalize("NFKC", name).casefold().strip()
    text = _WS.sub(" ", text)
    if not text:
        return ""
    head, sep, last = text.rpartition(" ")
    if len(last) > 3 and last.endswith("s") and not last.endswith("ss"):
        last = last[:-1]
    return f"{head}{sep}{last}"


def clean_text(
    value: str, *, field: str, max_len: int, allow_newlines: bool = False, required: bool = True
) -> str:
    """Strip, NFKC-normalize, reject control characters, and enforce length."""
    text = unicodedata.normalize("NFKC", value).strip()
    for ch in text:
        if unicodedata.category(ch) == "Cc" and not (allow_newlines and ch == "\n"):
            raise ValidationError(f"{field} contains characters that aren't allowed.")
    if required and not text:
        raise ValidationError(f"{field} can't be empty.")
    if len(text) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters.")
    return text
