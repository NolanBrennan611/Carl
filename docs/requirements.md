# Carl — Requirements

Status: **Approved design baseline v1.0** (2026-10-25)
Authoritative for: what the bot must do. Where this document and another disagree on *behavior*, this document wins; for *how*, see `architecture.md`, `database-design.md`, `reminder-system.md`.

---

## 1. Purpose

Carl is a private Discord bot for one household. It manages a shared grocery list, personal and shared to-do lists, and bill reminders. It runs as a single long-lived process with a local SQLite database and needs no paid services or AI APIs.

## 2. Users and roles

| Role | Who | Identified by |
|---|---|---|
| **Member** | Trusted household people (expected 2–5) | Member of the configured Discord server (`CARL_GUILD_ID`) **and** holds the configured household role (`CARL_HOUSEHOLD_ROLE_ID`) |
| **Admin** | One or two members who configure the bot | A Member who also holds `CARL_ADMIN_ROLE_ID`, **or** has the Discord *Manage Server* permission |
| **Operator** | The person who runs the host machine | Has shell access to the host; not a Discord role |
| **Outsider** | Anyone else | Everyone not above. Gets a permission error and nothing else |

## 3. Assumptions (documented defaults)

| ID | Assumption | Source |
|---|---|---|
| A-01 | One Discord server (guild), one household. The schema still keys every row by `guild_id` so a second guild never mixes data, but multi-guild operation is out of scope. | User answer |
| A-02 | All members share one household time zone, configured by an Admin (IANA name, e.g. `America/Chicago`). Per-user time zones are a later feature, added by a future migration. | User answer |
| A-03 | Dates entered by users default to US month/day order (`11/5` = November 5). Configurable via `CARL_DATE_ORDER=DMY`. | Default chosen |
| A-04 | Default currency `USD`. Amounts are informational only. | Default chosen |
| A-05 | Initial host: Google Cloud e2-micro Always Free VM (see `hosting-comparison.md`). Raspberry Pi is a supported later option. | User answer (no Pi yet) + research |
| A-06 | Bills and tasks have a **due date**, not a due time. Reminders are sent at a household-wide reminder time (default 09:00 local). | Default chosen |
| A-07 | Implementation language Python 3.12 with discord.py 2.7.x. | User answer |
| A-08 | No message-content intent, no member intent. Users interact only through slash commands and components. | Spec + design |

## 4. Functional requirements

Priority: **M** = must (MVP), **S** = should (MVP if cheap), **L** = later phase.

### 4.1 System / foundation (FR-S)

| ID | Requirement | Pri |
|---|---|---|
| FR-S-01 | Bot only responds to interactions from the configured guild. Commands are registered as guild commands for that guild only and are unavailable in DMs. | M |
| FR-S-02 | Every command and component interaction checks that the user is a Member (Admin for admin commands) before doing anything. | M |
| FR-S-03 | If the bot is added to any other guild, it logs a warning and leaves that guild. | M |
| FR-S-04 | Admins can set: reminder channel, household time zone, reminder time of day, default currency, default bill reminder offsets, and bill summary schedule. | M |
| FR-S-05 | Any Member can view current settings and `/carl help`. | M |
| FR-S-06 | Admins can view a status report: version, uptime, Discord connection state, last scheduler tick, database size, last backup time, counts of pending and failed notifications. It shows counts only, never bill contents. | M |
| FR-S-07 | Any Member can export household data plus their own personal data as a JSON file, delivered privately. | M |
| FR-S-08 | Database schema is managed by numbered migrations, applied automatically at startup after an automatic pre-migration backup. | M |
| FR-S-09 | Automatic daily backup of the database with retention (14 daily, 8 weekly). Admins can trigger a backup manually. | M |
| FR-S-10 | All data survives process restarts and host reboots. | M |
| FR-S-11 | A health signal (heartbeat file plus optional outbound ping URL) shows whether the scheduler is alive. | M |

### 4.2 Grocery list (FR-G)

| ID | Requirement | Pri |
|---|---|---|
| FR-G-01 | Add an item with name (required), optional quantity, unit, category, and note. Records which Member added it. | M |
| FR-G-02 | Add several items in one command using a comma-separated list (e.g. `milk, 2 lb apples, eggs`). Max 20 items. | M |
| FR-G-03 | Categories: `produce, dairy, meat_seafood, bakery, pantry, frozen, beverages, snacks, household, personal_care, other`. If none is given, a fixed keyword table picks one (deterministic), else `other`. | M |
| FR-G-04 | **Duplicate handling:** adding an item whose normalized name and normalized unit match an item still on the list *merges* instead of creating a duplicate. Quantities are summed when both are numbers. A missing quantity never erases an existing one. Differing notes are appended with ` · `. The response says exactly what was merged. Same name with a different unit creates a separate item, and the response mentions the existing one. | M |
| FR-G-05 | List needed items grouped by category. Filters: needed (default), purchased, all; optional category. | M |
| FR-G-06 | Check off one item by command, or several from the list view with a multi-select menu. | M |
| FR-G-07 | Uncheck a purchased item (return it to needed). If an identical needed item exists, merge per FR-G-04. | M |
| FR-G-08 | Edit an item's name, quantity, unit, category, note. Can clear the note or quantity. | M |
| FR-G-09 | Remove a single item (no confirmation needed; low stakes). | M |
| FR-G-10 | Clear all purchased items, but only after a confirmation button that names the number of items. | M |
| FR-G-11 | List is shared by all Members. Any Member may add, edit, check, uncheck, remove, or clear. | M |
| FR-G-12 | Separate lists per store. | L |
| FR-G-13 | **Live list:** a publicly posted list (`/grocery list`, shared by default) is kept up to date by editing that one message after every change; posting a new one replaces the old one. Best effort: a missing message is forgotten, never an error for the user. | M |
| FR-G-14 | Success confirmations are private embeds that delete themselves after about 10 seconds; errors are never auto-deleted. | M |

### 4.3 To-do list (FR-T)

| ID | Requirement | Pri |
|---|---|---|
| FR-T-01 | Create a task with title (required), optional due date, priority (`low`, `normal` default, `high`), notes, scope (`personal` default, `household`), and assignee (household tasks only, must be a Member). | M |
| FR-T-02 | Personal tasks are visible to and editable by their owner only. Household tasks are visible to and editable by all Members. | M |
| FR-T-03 | View tasks with filters: `mine` (default: my personal + household tasks assigned to me), `household`, `personal`, `today` (due today or overdue), `soon` (due in the next 7 days, incl. overdue), `overdue`, `completed` (completed in last 30 days). | M |
| FR-T-04 | Sort order: overdue first, then due date ascending (no due date last), then priority (high→low), then creation time. | M |
| FR-T-05 | Complete a task by command, or several from the list view with a multi-select menu. | M |
| FR-T-06 | Reopen a completed task. | M |
| FR-T-07 | Postpone a task by a preset (1 day, 3 days, 1 week, next Monday) or to a specific date. A task with no due date gets its due date set from today. | M |
| FR-T-08 | Edit title, due date (or clear it), priority, notes, scope, assignee. | M |
| FR-T-09 | Delete a task, but only after a confirmation button. For a recurring task, the confirmation offers "Delete this one" and "Delete and stop repeating". | M |
| FR-T-10 | **Recurring tasks** (requires due date): when completed, the next instance is created with the next due date per the recurrence rule. Missed occurrences in the past are skipped (the next due date is the first occurrence ≥ today). Completing the same instance twice never creates two next instances. | S (planned for Phase 3) |
| FR-T-11 | Task reminders by DM at reminder time. | L |

### 4.4 Bills (FR-B)

| ID | Requirement | Pri |
|---|---|---|
| FR-B-01 | Create a bill with name (required), first due date (required), optional amount, currency (default from settings), recurrence, reminder offsets, notes, scope (`personal` default, `household`). | M |
| FR-B-02 | Recurrence choices: none (one-time), daily, weekly, biweekly, monthly, monthly on last day, quarterly, yearly, plus an optional "every N" multiplier. | M |
| FR-B-03 | Month-end rule: a monthly bill anchored on day 29–31 falls on the last day of shorter months and **returns to the anchor day** in longer months (no drift). A yearly bill anchored on Feb 29 falls on Feb 28 in non-leap years. | M |
| FR-B-04 | Reminder offsets: a list of 0–5 whole days before the due date, each 0–60 (0 = on the due date). Default from settings (initially `3,0`). Reminders fire at the household reminder time in the household time zone. | M |
| FR-B-05 | One "overdue" notice the day after the due date if still unpaid. | M |
| FR-B-06 | **Duplicate prevention:** two active bills with the same normalized name in the same scope are rejected with a pointer to the existing bill. | M |
| FR-B-07 | Mark the earliest unpaid occurrence of a bill as paid (optional paid date, actual amount, note). Also from a **Mark paid** button on every reminder message. | M |
| FR-B-08 | Undo the most recent payment of a bill (mark unpaid). | M |
| FR-B-09 | Skip an occurrence (e.g. waived this month). Skipped occurrences send no reminders and do not count as overdue. | S |
| FR-B-10 | View: all bills with next due date; upcoming (next N days, default 30, max 60); overdue; payment history for one bill or all (default last 12). | M |
| FR-B-11 | Edit name, amount, currency, notes, offsets, scope, recurrence, next due date. Schedule changes regenerate future unpaid occurrences and their reminders. Past unpaid (overdue) occurrences are kept. | M |
| FR-B-12 | Delete a bill after confirmation. Default deletion archives the bill (history kept for export). A `purge` option permanently deletes the bill and its history after a second, explicitly worded confirmation. | M |
| FR-B-13 | Personal bill reminders go by DM to the owner. Household bill reminders go to the configured reminder channel. | M |
| FR-B-14 | Optional daily or weekly bill summary: household summary to the reminder channel; personal summary by DM to each Member with active personal bills. A daily summary with nothing to report is not sent. | M |
| FR-B-15 | The bot never connects to banks, processes payments, or stores payment credentials. Notes fields carry a hint not to store account numbers. | M |
| FR-B-16 | Subscriptions, birthdays, custom reminders reusing the reminder engine. | L |

## 5. Non-functional requirements (NFR)

| ID | Requirement | Measure |
|---|---|---|
| NFR-01 Reliability | Reminders survive restarts; missed reminders are reconciled per `reminder-system.md` §7. | Recovery tests in Phase 4/5 pass |
| NFR-02 Timeliness | When the bot is healthy, a reminder is sent within 90 s of its scheduled time. | Scheduler tick ≤ 30 s; tested with fake clock |
| NFR-03 Delivery honesty | A notification is recorded as `sent` only after Discord's API returns success with a message ID. Guarantee is *at-least-once attempt with duplicate suppression*, not exactly-once. | Dispatcher tests |
| NFR-04 Determinism | Core features work with no AI or other paid API. | No such dependency in `pyproject.toml` core group |
| NFR-05 Resource use | Steady-state RSS ≤ 150 MB; idle CPU < 2% on an e2-micro or Raspberry Pi 4. | Measured in Phase 5 |
| NFR-06 Portability | Same container image (amd64 + arm64) runs on GCP, Oracle, Pi, or any VPS. Business logic never imports `discord`. | Import-lint test |
| NFR-07 Privacy | Logs contain IDs and command names, never item names, task titles, bill names, amounts, or notes. Bill data is only shown in ephemeral replies, DMs to owners, or the private reminder channel. | Log-redaction test |
| NFR-08 Integrity | SQLite in WAL mode with foreign keys, `STRICT` tables, CHECK constraints; every multi-row change in one transaction. | Schema tests |
| NFR-09 Usability | Every common action reachable in ≤ 1 slash command with ≤ 3 typed options; autocomplete for picking existing records; lists usable on a phone. | Manual mobile checklist, Phase 5 |
| NFR-10 Testability | Domain and service code ≥ 90% line coverage; the whole suite runs offline in < 60 s. | `pytest --cov` |
| NFR-11 Maintainability | One process, one database file, ≤ 6 runtime dependencies. | `pyproject.toml` review |

## 6. User stories with acceptance criteria

Format: *As a … I want … so that …* → **AC** (Given/When/Then). IDs map to the implementation plan.

### Grocery
- **US-G1** As a Member I want to add "milk" quickly from my phone so I don't forget it.
  **AC:** Given an empty list, when I run `/grocery add item:milk`, then an ephemeral reply confirms "Added **milk** (Dairy)" and `/grocery list` shows it under Dairy.
- **US-G2** As a Member I want duplicates merged so the list stays clean.
  **AC:** Given "apples 2 lb" is needed, when anyone adds "Apples" qty 1 unit "lbs", then one item remains with quantity 3 lb and the reply says "Merged with existing **apples**: now 3 lb".
  **AC:** Given "apples 2 lb" is needed, when anyone adds "apples" qty 1 unit "bag", then two items exist and the reply notes "Also on the list: apples (2 lb)".
- **US-G3** As a shopper I want to tick off several items at once in the store.
  **AC:** When I pick 3 items in the list view's select menu, then all 3 become purchased in one transaction and the list view refreshes.
- **US-G4** As a Member I want to undo a mistaken check-off.
  **AC:** `/grocery uncheck` returns the item to needed with quantity and note intact.
- **US-G5** As a Member I want to clear purchased items without accidental loss.
  **AC:** `/grocery clear` shows "Remove 7 purchased items?" with Clear/Cancel buttons. Nothing is deleted until Clear is pressed by the same user within 2 minutes. Cancel or timeout deletes nothing.

### To-do
- **US-T1** As a Member I want private tasks no one else sees.
  **AC:** A personal task created by A never appears in B's lists, autocomplete, or export, and B cannot act on it even by forging its ID (reply: "Task not found.").
- **US-T2** As a Member I want shared chores assigned to people.
  **AC:** A household task with assignee B appears in B's `mine` filter and in everyone's `household` filter.
- **US-T3** As a Member I want to see what's due today.
  **AC:** `/todo list filter:today` shows only open visible tasks due today or earlier, overdue ones marked ⚠ and listed first.
- **US-T4** As a Member I want weekly recurring chores.
  **AC:** Completing "Take out trash" (weekly, due Mon 2026-11-02) on 2026-11-02 creates an open instance due 2026-11-09. Completing it on 2026-11-20 (late) creates the next instance due 2026-11-23, skipping 11-16. Pressing Done twice creates only one next instance.
- **US-T5** As a Member I want to postpone tasks.
  **AC:** `/todo postpone task:X by:1 week` moves the due date +7 days and the reply shows old → new date.

### Bills
- **US-B1** As a Member I want reminders before a bill is due.
  **AC:** Given household zone `America/Chicago`, reminder time 09:00, offsets `3,0`, a household bill due 2026-11-01, then reminders are posted to the reminder channel at 2026-10-29 09:00 CDT (14:00Z) and 2026-11-01 09:00 CST (15:00Z, after the DST change), each with a Mark paid button.
- **US-B2** As a Member I want month-end bills handled correctly.
  **AC:** A monthly bill first due 2027-01-31 has occurrences 2027-02-28, 2027-03-31, 2027-04-30. A yearly bill first due 2028-02-29 has its next occurrence on 2029-02-28.
- **US-B3** As a Member I want marking paid to stop reminders.
  **AC:** After Mark paid on an occurrence, its pending reminders become `cancelled` and no further reminder or overdue notice is sent for it.
- **US-B4** As a Member I want reminders to arrive after the bot was down.
  **AC:** Given the bot was offline from before the 3-day reminder until 2 hours after it, on restart exactly one reminder labeled "Delayed reminder" is sent for that occurrence. If the bot comes back after the due date, only the overdue notice is sent.
- **US-B5** As a Member I want no duplicate bills.
  **AC:** Creating "Electric" when an active household bill "electric " exists is rejected: "A household bill named **Electric** already exists. Use `/bill edit`."
- **US-B6** As a Member I want payment history.
  **AC:** `/bill history bill:Electric` lists paid occurrences, newest first: due date, paid date, amount, who marked it.
- **US-B7** As a Member with a personal bill I want reminders only I see.
  **AC:** A personal bill's reminders arrive by DM to the owner only. If DMs are blocked, the notification is marked `failed` (`dm_forbidden`), it is **not** posted to the shared channel, and `/bill upcoming` shows "⚠ last reminder could not be delivered".

### Admin / ops
- **US-A1** As an Admin I want to configure the bot without touching the server.
  **AC:** `/carl setup channel:#bills timezone:America/Chicago reminder_time:08:30` saves settings, re-plans pending reminders to the new time, and confirms the next three scheduled reminder times.
- **US-A2** As an Operator I want restore to be reliable.
  **AC:** Following `security-and-operations.md` §8 on a fresh host, restoring the latest backup reproduces all lists and bills, and no reminder already marked `sent` is sent again.
- **US-A3** As an outsider in the server, I can't use the bot.
  **AC:** A server member without the household role gets an ephemeral "You don't have access to Carl. Ask an admin for the household role." for every command and button.

## 7. Out of scope (v1)

Bank or payment integrations; storing card or account numbers; multi-household or multi-guild support; web dashboard; message-content-based commands; AI parsing in core; voice; calendar sync (later); per-user time zones (later).

## 8. Requirement traceability (summary)

Full mapping lives in `implementation-plan.md` §9. Every FR above maps to at least one table (`database-design.md`), one command (`discord-commands.md`), one test group, and one phase acceptance criterion.
