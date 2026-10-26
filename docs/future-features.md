# Carl — Future Features

Status: **Proposal list v1.0** (2026-10-25). Nothing here is in scope until the user picks it for Phase 6+. Each pick gets a short design note appended below and approved before coding.

Complexity: **S** ≈ ≤ 1 day for the implementer, **M** ≈ 2–4 days, **L** ≈ a week or more, or new external dependencies.

---

## 1. MVP (Phases 1–5) — for reference

Grocery list, to-do list (with recurring tasks), bills with reliable reminders and summaries, settings, export, backups, health checks. That's already a complete, useful bot; resist adding more before it has run reliably for a few weeks.

## 2. Evaluation

| # | Feature | Usefulness | Complexity | Dependencies / reuse | Privacy implications | Recommended phase |
|---|---|---|---|---|---|---|
| 1 | **Daily briefing** (one DM per person each morning: tasks due today/overdue, bills due soon, grocery count) | High: one glance per day | **S** | Reuses tasks/bills queries + `notifications` (new kind `daily_briefing`, per-user opt-in) | DM only; personal data stays with its owner | **6a (first pick)** |
| 2 | **Custom reminders** (`/remind add text:"Call mom" when:"fri 18:00"`), deterministic parser | High | **M** | New `reminders` table, reuses planner/dispatcher; date grammar extended with times | Personal by default | **6a** |
| 3 | **Birthdays & anniversaries** | Medium–High | **S** (on top of #2) | Yearly recurrence (exists, incl. Feb 29); offsets like bills | Names/dates of people; household scope optional | **6a** |
| 4 | **Subscription renewals** | Medium | **S** | A bill with a `category=subscription` flag + "cancel by" offset; or a reminder type | Same as bills | **6b** (could just use bills today) |
| 5 | **Household chores with rotation** (round-robin assignee on each recurrence) | High for shared homes | **M** | Extends recurring tasks: `rotation_json` list of user IDs; next assignee on completion | Low | **6b** |
| 6 | **Shopping lists by store** | Medium | **S–M** | `store` column + filter + migration; merge key adds store | Low | **6b** |
| 7 | **Weekly planning summary** (Sunday post: upcoming week's bills, chores, events) | Medium | **S** | Extends summaries | Household channel only for household data | **6b** |
| 8 | **Appointment & event reminders** (date + time + location) | Medium | **M** | Like #2 with times; time-of-day DST handling already designed | Personal/household scope | **6b** |
| 9 | **Habit tracking** (daily check-ins, streaks) | Medium (personal) | **M** | New tables, buttons on a daily DM | Personal only | **7** |
| 10 | **Meal planning & recipe links** (week grid, "add ingredients to grocery list") | Medium | **M–L** | New tables; link to grocery merge; no scraping (store URLs only) | Low | **7** |
| 11 | **Pantry/household inventory** (what's at home, low-stock → grocery) | Medium | **L** | New domain; overlaps grocery; needs discipline to keep updated | Low | **7 / maybe never** |
| 12 | **Household expense tracking & shared summaries** (who paid what, who owes whom) | Medium | **L** | New ledger tables, split rules, currency rounding; must stay manual (no bank links) | Sensitive financial data; personal vs shared views | **7**, careful design needed |
| 13 | **Calendar integration** (export ICS feed of bills/tasks; or Google Calendar sync) | Medium | ICS export **S**; two-way sync **L** | ICS needs no service: `/carl calendar` sends an `.ics` file. Live feeds need an inbound HTTPS endpoint (a public port; changes the security model). Google sync needs OAuth + API | ICS file is private if sent ephemerally; a URL feed is a capability URL (secret) | ICS file: **6b**; live sync: **later / maybe never** |
| 14 | **Package delivery tracking** | Low–Medium | **L** | Needs a third-party tracking API (free tiers are limited, and terms vary by carrier); polling | Addresses and tracking numbers are sensitive | **Not recommended** for now |
| 15 | **Backup & export improvements** (CSV per table, import from export, scheduled export DM to admin) | Medium | **S–M** | Export exists; import needs validation and conflict rules | Export files contain private data; deliver ephemerally only | Import: **6b** |
| 16 | **Natural-language input via AI** (optional) | Nice-to-have | **M** | Optional module + API key; core unaffected (ADR-011); feeds parsed fields into the same service calls, with a confirmation step | Sends text to an AI provider: opt-in, disclosed, off by default | **Later, optional** |
| 17 | **Per-user time zones** | Needed only if someone moves | **M** | Migration: `user_settings`; personal reminders resolve the owner's zone | None | When needed |
| 18 | **Grocery "usuals"** (one tap to re-add frequently bought items) | High convenience | **S** | Query on purchase history (purchased items kept until cleared; add `purchase_count` table) | Low | **6a** |

## 3. Suggested sequence after MVP

- **6a:** Daily briefing → Grocery usuals → Custom reminders → Birthdays.
- **6b:** Chore rotation → Shopping by store → Weekly planning → Subscriptions → ICS export → Event reminders → Import.
- **7:** Habits, meal planning, expense tracking (needs its own design doc).
- **Not planned:** package tracking, two-way calendar sync, pantry inventory (revisit if asked).

## 4. Design notes for accepted features

_(empty: append here when a feature is approved)_
