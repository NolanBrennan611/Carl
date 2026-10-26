"""custom_id scheme (docs/discord-commands.md section 8): carl:v1:<domain>:<action>:<args...>.

Discord allows 100 characters. IDs must be unique within one message.
"""

from __future__ import annotations

PREFIX = "carl:v1"
MAX_LEN = 100
NONE_TOKEN = "_"  # stands in for "no value" (e.g. no category filter)


def build(*parts: str | int) -> str:
    texts = [str(p) for p in parts]
    if any(":" in t or not t for t in texts):
        raise ValueError(f"custom_id parts must be non-empty and contain no ':': {texts}")
    custom_id = ":".join([PREFIX, *texts])
    if len(custom_id) > MAX_LEN:
        raise ValueError(f"custom_id is {len(custom_id)} characters (max {MAX_LEN})")
    return custom_id


def parse(custom_id: str) -> list[str] | None:
    """The parts after the prefix, or None if this isn't one of our IDs."""
    head = PREFIX + ":"
    if not custom_id.startswith(head):
        return None
    return custom_id[len(head) :].split(":")


def cat_token(category: str | None) -> str:
    return category or NONE_TOKEN


def cat_from_token(token: str) -> str | None:
    return None if token == NONE_TOKEN else token
