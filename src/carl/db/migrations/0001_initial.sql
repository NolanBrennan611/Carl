-- 0001_initial: full Phase 1-5 schema (docs/database-design.md section 4).
-- schema_migrations itself is created by the migration runner.

CREATE TABLE app_state (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE guild_settings (
  guild_id                  INTEGER PRIMARY KEY,
  timezone                  TEXT NOT NULL,
  reminder_channel_id       INTEGER,
  reminder_time             TEXT NOT NULL DEFAULT '09:00'
                              CHECK (reminder_time GLOB '[0-2][0-9]:[0-5][0-9]'),
  default_currency          TEXT NOT NULL DEFAULT 'USD' CHECK (length(default_currency) = 3),
  default_bill_offsets_json TEXT NOT NULL DEFAULT '[3,0]' CHECK (json_valid(default_bill_offsets_json)),
  summary_frequency         TEXT NOT NULL DEFAULT 'off'
                              CHECK (summary_frequency IN ('off','daily','weekly')),
  summary_weekday           INTEGER NOT NULL DEFAULT 6 CHECK (summary_weekday BETWEEN 0 AND 6),
  summary_time              TEXT NOT NULL DEFAULT '08:00'
                              CHECK (summary_time GLOB '[0-2][0-9]:[0-5][0-9]'),
  date_order                TEXT NOT NULL DEFAULT 'MDY' CHECK (date_order IN ('MDY','DMY')),
  created_at                TEXT NOT NULL,
  updated_at                TEXT NOT NULL
) STRICT;

CREATE TABLE grocery_items (
  id                    INTEGER PRIMARY KEY,
  guild_id              INTEGER NOT NULL,
  name                  TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
  name_normalized       TEXT NOT NULL,
  quantity              REAL CHECK (quantity IS NULL OR (quantity > 0 AND quantity <= 9999)),
  unit                  TEXT CHECK (unit IS NULL OR length(unit) <= 20),
  unit_normalized       TEXT NOT NULL DEFAULT '',
  category              TEXT NOT NULL DEFAULT 'other' CHECK (category IN
                          ('produce','dairy','meat_seafood','bakery','pantry','frozen',
                           'beverages','snacks','household','personal_care','other')),
  note                  TEXT CHECK (note IS NULL OR length(note) <= 300),
  status                TEXT NOT NULL DEFAULT 'needed' CHECK (status IN ('needed','purchased')),
  added_by_user_id      INTEGER NOT NULL,
  purchased_by_user_id  INTEGER,
  purchased_at          TEXT,
  created_at            TEXT NOT NULL,
  updated_at            TEXT NOT NULL,
  CHECK ((status = 'purchased') = (purchased_at IS NOT NULL))
) STRICT;

CREATE UNIQUE INDEX ux_grocery_needed_key
  ON grocery_items (guild_id, name_normalized, unit_normalized) WHERE status = 'needed';
CREATE INDEX ix_grocery_list ON grocery_items (guild_id, status, category, name_normalized);

CREATE TABLE tasks (
  id                    INTEGER PRIMARY KEY,
  guild_id              INTEGER NOT NULL,
  scope                 TEXT NOT NULL CHECK (scope IN ('personal','household')),
  owner_user_id         INTEGER NOT NULL,
  assignee_user_id      INTEGER,
  title                 TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  notes                 TEXT CHECK (notes IS NULL OR length(notes) <= 1000),
  priority              TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high')),
  due_date              TEXT,
  status                TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','done')),
  completed_at          TEXT,
  completed_by_user_id  INTEGER,
  recurrence_json       TEXT CHECK (recurrence_json IS NULL OR json_valid(recurrence_json)),
  series_id             INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  created_at            TEXT NOT NULL,
  updated_at            TEXT NOT NULL,
  CHECK (scope = 'household' OR assignee_user_id IS NULL),
  CHECK (recurrence_json IS NULL OR due_date IS NOT NULL),
  CHECK ((status = 'done') = (completed_at IS NOT NULL))
) STRICT;

CREATE INDEX ix_tasks_visible ON tasks (guild_id, status, scope, owner_user_id, due_date);
CREATE INDEX ix_tasks_assignee ON tasks (guild_id, assignee_user_id, status);
CREATE INDEX ix_tasks_series ON tasks (series_id);

CREATE TABLE bills (
  id                      INTEGER PRIMARY KEY,
  guild_id                INTEGER NOT NULL,
  scope                   TEXT NOT NULL CHECK (scope IN ('personal','household')),
  owner_user_id           INTEGER NOT NULL,
  name                    TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
  name_normalized         TEXT NOT NULL,
  amount_minor            INTEGER CHECK (amount_minor IS NULL OR amount_minor BETWEEN 0 AND 100000000000),
  currency                TEXT NOT NULL CHECK (length(currency) = 3),
  notes                   TEXT CHECK (notes IS NULL OR length(notes) <= 1000),
  first_due_date          TEXT NOT NULL,
  recurrence_json         TEXT CHECK (recurrence_json IS NULL OR json_valid(recurrence_json)),
  reminder_offsets_json   TEXT CHECK (reminder_offsets_json IS NULL OR json_valid(reminder_offsets_json)),
  archived_at             TEXT,
  created_at              TEXT NOT NULL,
  updated_at              TEXT NOT NULL
) STRICT;

CREATE UNIQUE INDEX ux_bills_active_name ON bills (
  guild_id, scope,
  (CASE WHEN scope = 'personal' THEN owner_user_id ELSE 0 END),
  name_normalized
) WHERE archived_at IS NULL;
CREATE INDEX ix_bills_guild ON bills (guild_id, archived_at, scope, owner_user_id);

CREATE TABLE bill_occurrences (
  id                  INTEGER PRIMARY KEY,
  bill_id             INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  guild_id            INTEGER NOT NULL,
  due_date            TEXT NOT NULL,
  amount_minor        INTEGER,
  status              TEXT NOT NULL DEFAULT 'unpaid' CHECK (status IN ('unpaid','paid','skipped')),
  paid_at             TEXT,
  paid_on_date        TEXT,
  paid_by_user_id     INTEGER,
  paid_amount_minor   INTEGER CHECK (paid_amount_minor IS NULL OR paid_amount_minor >= 0),
  payment_note        TEXT CHECK (payment_note IS NULL OR length(payment_note) <= 300),
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  UNIQUE (bill_id, due_date),
  CHECK ((status = 'paid') = (paid_at IS NOT NULL))
) STRICT;

CREATE INDEX ix_occ_due ON bill_occurrences (guild_id, status, due_date);

CREATE TABLE notifications (
  id                  INTEGER PRIMARY KEY,
  guild_id            INTEGER NOT NULL,
  kind                TEXT NOT NULL CHECK (kind IN ('bill_reminder','bill_overdue','bill_summary')),
  dedupe_key          TEXT NOT NULL UNIQUE,
  bill_id             INTEGER REFERENCES bills(id) ON DELETE CASCADE,
  bill_occurrence_id  INTEGER REFERENCES bill_occurrences(id) ON DELETE SET NULL,
  offset_days         INTEGER,
  target_type         TEXT NOT NULL CHECK (target_type IN ('household_channel','user_dm')),
  target_user_id      INTEGER,
  scheduled_for       TEXT NOT NULL,
  expires_at          TEXT NOT NULL,
  status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
                        ('pending','sending','sent','failed','cancelled','skipped','expired')),
  attempt_count       INTEGER NOT NULL DEFAULT 0,
  next_attempt_at     TEXT NOT NULL,
  last_error_code     TEXT,
  last_error_at       TEXT,
  status_reason       TEXT,
  discord_channel_id  INTEGER,
  discord_message_id  INTEGER,
  sent_at             TEXT,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  CHECK (target_type = 'household_channel' OR target_user_id IS NOT NULL),
  CHECK ((status = 'sent') = (discord_message_id IS NOT NULL))
) STRICT;

CREATE INDEX ix_notif_due ON notifications (status, next_attempt_at);
CREATE INDEX ix_notif_occ ON notifications (bill_occurrence_id, status);
CREATE INDEX ix_notif_guild_status ON notifications (guild_id, status);

CREATE TABLE audit_log (
  id             INTEGER PRIMARY KEY,
  guild_id       INTEGER NOT NULL,
  actor_user_id  INTEGER,
  action         TEXT NOT NULL,
  entity_type    TEXT NOT NULL,
  entity_id      INTEGER,
  details_json   TEXT CHECK (details_json IS NULL OR json_valid(details_json)),
  at             TEXT NOT NULL
) STRICT;

CREATE INDEX ix_audit_guild_at ON audit_log (guild_id, at);
