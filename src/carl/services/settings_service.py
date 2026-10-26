"""Household settings (FR-S-04, FR-S-05)."""

from __future__ import annotations

from dataclasses import replace

from carl.clock import Clock
from carl.config import Settings
from carl.db.connection import Database
from carl.domain import bills, money, timeutil
from carl.domain.errors import Forbidden, NotFound, ValidationError
from carl.domain.models import Actor, GuildSettings
from carl.repositories.audit_repo import AuditRepo
from carl.repositories.settings_repo import SettingsRepo


class SettingsService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        settings_repo: SettingsRepo,
        audit_repo: AuditRepo,
    ) -> None:
        self.db = db
        self.clock = clock
        self.repo = settings_repo
        self.audit = audit_repo

    def _now(self) -> str:
        return timeutil.to_db_instant(timeutil.utc_now(self.clock))

    async def seed(self, env: Settings) -> GuildSettings:
        """Create the guild's settings from env defaults if they don't exist yet."""
        async with self.db.transaction():
            defaults = GuildSettings(
                guild_id=env.guild_id,
                timezone=env.default_timezone,
                reminder_channel_id=None,
                reminder_time="09:00",
                default_currency=env.default_currency,
                default_bill_offsets=(3, 0),
                summary_frequency="off",
                summary_weekday=6,
                summary_time="08:00",
                date_order=env.date_order,
            )
            await self.repo.insert_if_absent(defaults, self._now())
        return await self.get(env.guild_id)

    async def get(self, guild_id: int) -> GuildSettings:
        found = await self.repo.get(guild_id)
        if found is None:
            raise NotFound("Carl isn't set up for this server yet.")
        return found

    async def setup(
        self,
        actor: Actor,
        *,
        reminder_channel_id: int | None = None,
        timezone: str | None = None,
        reminder_time: str | None = None,
        currency: str | None = None,
        default_remind: str | None = None,
        date_order: str | None = None,
    ) -> GuildSettings:
        """Admin-only. Only the provided fields change. Returns the updated settings."""
        if not actor.is_admin:
            raise Forbidden("Only Carl admins can do that.")

        current = await self.get(actor.guild_id)
        changes: dict[str, object] = {}
        changed_fields: list[str] = []

        if reminder_channel_id is not None:
            changes["reminder_channel_id"] = reminder_channel_id
            changed_fields.append("reminder_channel")
        if timezone is not None:
            timeutil.get_zone(timezone.strip())
            changes["timezone"] = timezone.strip()
            changed_fields.append("timezone")
        if reminder_time is not None:
            parsed = timeutil.parse_hhmm(reminder_time)
            changes["reminder_time"] = parsed.strftime("%H:%M")
            changed_fields.append("reminder_time")
        if currency is not None:
            changes["default_currency"] = money.normalize_currency(currency)
            changed_fields.append("currency")
        if default_remind is not None:
            changes["default_bill_offsets"] = bills.parse_offsets(default_remind)
            changed_fields.append("default_remind")
        if date_order is not None:
            value = date_order.strip().upper()
            if value not in ("MDY", "DMY"):
                raise ValidationError("Date order must be MDY or DMY.")
            changes["date_order"] = value
            changed_fields.append("date_order")

        if not changes:
            raise ValidationError("Nothing to change. Provide at least one option.")

        updated = replace(current, **changes)  # type: ignore[arg-type]
        now = self._now()
        async with self.db.transaction():
            await self.repo.update(updated, now)
            await self.audit.add(
                guild_id=actor.guild_id,
                actor_user_id=actor.user_id,
                action="settings.update",
                entity_type="guild_settings",
                entity_id=actor.guild_id,
                details={"fields": changed_fields},
                at=now,
            )
        # Phase 4: re-plan pending notifications here (docs/reminder-system.md section 5.4).
        return updated
