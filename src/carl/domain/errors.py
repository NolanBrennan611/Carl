"""Typed errors raised by services. The Discord layer maps these to user messages."""


class CarlError(Exception):
    """Base class. `message` is safe to show to the user."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(CarlError):
    """Record missing, or not visible to the actor (deliberately indistinguishable)."""


class Forbidden(CarlError):
    """Actor is not allowed to do this."""


class ValidationError(CarlError):
    """Input failed validation."""


class Conflict(CarlError):
    """Request conflicts with existing data (duplicate, collision)."""
