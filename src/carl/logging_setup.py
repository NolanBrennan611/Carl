"""Logging: key=value lines on stdout, with a backstop filter that masks token-like strings."""

from __future__ import annotations

import logging
import re
import sys
from datetime import UTC, datetime

# Discord bot tokens look like <base64 id>.<6 chars>.<27+ chars>
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6,7}\.[A-Za-z0-9_-]{27,}")
_URL_SECRET_RE = re.compile(r"(https?://hc-ping\.com/)\S+")


def mask(text: str) -> str:
    text = _TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    return _URL_SECRET_RE.sub(r"\1[REDACTED]", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask(record.getMessage())
        record.args = None
        return True


class DropVoiceNoise(logging.Filter):
    """Carl never uses voice; discord.py's 'voice will NOT be supported' warnings are noise."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "voice will NOT be supported" not in record.getMessage()


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%S.")
        ts += f"{int(record.msecs):03d}Z"
        line = f"{ts} {record.levelname} {record.name} {record.getMessage()}"
        if record.exc_info:
            line += "\n" + mask(self.formatException(record.exc_info))
        return line


def quiet_noisy_loggers(level: str = "INFO") -> None:
    """Libraries that would write household data into the logs, whatever the log level.

    aiosqlite logs every SQL statement *with its bound values* at DEBUG, which would include
    item names, task titles, bill names, amounts and notes.
    """
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("discord").setLevel("INFO" if level == "DEBUG" else "WARNING")


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(KeyValueFormatter())
    handler.addFilter(DropVoiceNoise())
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    quiet_noisy_loggers(level)
