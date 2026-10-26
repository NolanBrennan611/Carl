"""Map exceptions to user-facing messages (docs/discord-commands.md section 9)."""

from __future__ import annotations

import logging
import secrets

from carl.domain.errors import CarlError

log = logging.getLogger("carl.errors")


def new_error_id() -> str:
    return "E-" + secrets.token_hex(2).upper()


def message_for(exc: BaseException) -> str:
    """Safe text for the user. Unexpected errors are logged with a short reference ID."""
    if isinstance(exc, CarlError):
        return exc.message
    error_id = new_error_id()
    log.error("unexpected_error ref=%s type=%s", error_id, type(exc).__name__, exc_info=exc)
    return f"Something went wrong (ref `{error_id}`). It's been logged."
