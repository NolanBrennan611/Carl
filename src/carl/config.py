"""Environment configuration. Fails fast with messages naming the bad variable."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import available_timezones


class ConfigError(Exception):
    """Invalid or missing configuration."""


class SecretStr:
    """Wraps a secret so repr()/str() never reveal it."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"SecretStr('{self._mask()}')"

    def __str__(self) -> str:
        return self._mask()

    def _mask(self) -> str:
        return "****" + self._value[-4:] if len(self._value) >= 8 else "****"

    def __bool__(self) -> bool:
        return bool(self._value)


@dataclass(frozen=True)
class Settings:
    discord_token: SecretStr
    guild_id: int
    household_role_id: int
    admin_role_id: int | None
    default_timezone: str
    default_currency: str
    date_order: str
    data_dir: Path
    backup_time: str
    log_level: str
    healthcheck_url: SecretStr | None
    env: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "carl.db"


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable {name}")
    return value


def _snowflake(env: Mapping[str, str], name: str, *, required: bool) -> int | None:
    raw = _required(env, name) if required else env.get(name, "").strip()
    if not raw:
        return None
    if not raw.isdigit() or int(raw) <= 0:
        raise ConfigError(f"{name} must be a numeric Discord ID")
    return int(raw)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from a mapping (defaults to os.environ)."""
    env = os.environ if env is None else env

    token = _required(env, "DISCORD_TOKEN")
    guild_id = _snowflake(env, "CARL_GUILD_ID", required=True)
    role_id = _snowflake(env, "CARL_HOUSEHOLD_ROLE_ID", required=True)
    admin_role_id = _snowflake(env, "CARL_ADMIN_ROLE_ID", required=False)
    assert guild_id is not None and role_id is not None

    tz = _required(env, "CARL_DEFAULT_TIMEZONE")
    if tz not in available_timezones():
        raise ConfigError(f"CARL_DEFAULT_TIMEZONE '{tz}' is not a known IANA time zone")

    currency = env.get("CARL_DEFAULT_CURRENCY", "USD").strip().upper() or "USD"
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ConfigError("CARL_DEFAULT_CURRENCY must be a 3-letter code like USD")

    date_order = env.get("CARL_DATE_ORDER", "MDY").strip().upper() or "MDY"
    if date_order not in ("MDY", "DMY"):
        raise ConfigError("CARL_DATE_ORDER must be MDY or DMY")

    backup_time = env.get("CARL_BACKUP_TIME", "03:30").strip() or "03:30"
    if not _HHMM.match(backup_time):
        raise ConfigError("CARL_BACKUP_TIME must be HH:MM (24-hour)")

    level = env.get("CARL_LOG_LEVEL", "INFO").strip().upper() or "INFO"
    if level not in _LEVELS:
        raise ConfigError(f"CARL_LOG_LEVEL must be one of {', '.join(sorted(_LEVELS))}")

    app_env = env.get("CARL_ENV", "dev").strip().lower() or "dev"
    if app_env not in ("dev", "prod"):
        raise ConfigError("CARL_ENV must be dev or prod")

    hc = env.get("CARL_HEALTHCHECK_URL", "").strip()
    data_dir = Path(env.get("CARL_DATA_DIR", "").strip() or "./data")

    return Settings(
        discord_token=SecretStr(token),
        guild_id=guild_id,
        household_role_id=role_id,
        admin_role_id=admin_role_id,
        default_timezone=tz,
        default_currency=currency,
        date_order=date_order,
        data_dir=data_dir,
        backup_time=backup_time,
        log_level=level,
        healthcheck_url=SecretStr(hc) if hc else None,
        env=app_env,
    )
