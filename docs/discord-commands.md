# Carl — Discord Commands & Interaction Design

Status: **Approved design baseline v1.0** (2026-10-25)
All commands are **guild commands** registered only in `CARL_GUILD_ID`, with `contexts = [guild]` (unavailable in DMs). Names and option names below are exact.

---

## 1. Principles

1. **Four top-level groups:** `/grocery`, `/todo`, `/bill`, `/carl`. Verbs are consistent across groups: `add`, `list`, `edit`, `remove`/`delete`, `done`/`check`.
2. **Pick, don't type IDs.** Every option that refers to an existing record uses **autocomplete**. Its suggestion `value` is the record ID as a string, its `name` is human-readable. The command handler re-validates the ID against the user's scope (autocomplete values can be forged).
3. **Private by default.** All replies are **ephemeral** unless stated. Bill content never appears in a public message except in the designated reminder channel.
4. **Phone-first lists.** Lists are embeds with a multi-select for bulk actions and ◀ ▶ buttons (only when there is more than one page). No typing needed after the first command.
5. **Destructive = confirm.** Bulk or irreversible deletes use a Confirm/Cancel button pair that only the invoking user can press, valid for 2 minutes.
6. **Components survive restarts.** All buttons and selects are `discord.ui.DynamicItem`s whose `custom_id` encodes everything needed (see §8).
7. **Terminology:** "item" (grocery), "task" (to-do), "bill" (definition), "payment"/"due date" (occurrence), "household" (shared), "personal" (only you).

## 2. Discord application configuration

| Setting | Value | Why |
|---|---|---|
| OAuth2 scopes | `bot`, `applications.commands` | Slash commands + bot user |
| Bot permissions (integer computed by implementer) | View Channels, Send Messages, Embed Links, Read Message History, Attach Files | Post reminders; read *its own* recent messages for duplicate check (§`reminder-system.md` 8); send export file |
| Gateway intents | `GUILDS` only (`discord.Intents.none()` then `guilds = True`) | Needed for guild/channel/role cache |
| Privileged intents | **None.** `MESSAGE_CONTENT`, `GUILD_MEMBERS`, `GUILD_PRESENCES` all **off** | Slash-command interactions carry the invoking member and their role IDs; user-type options carry resolved members. Nothing needs message text or a member list. |
| Public Bot toggle | **Off** | Only the owner can invite it |
| Requires OAuth2 Code Grant | Off | Not needed |
| Install contexts | Guild install only | No user-install / DM usage |

Reminder channel permissions: give the bot role View Channel, Send Messages, Embed Links, Read Message History on that channel. Make the channel visible only to the household role.

## 3. Authorization matrix

Actor resolution (`discord_ui/auth.py`): `interaction.guild_id == CARL_GUILD_ID` and `interaction.user` is a `Member` whose `roles` contain `CARL_HOUSEHOLD_ROLE_ID` → **Member**. Member and (has `CARL_ADMIN_ROLE_ID` or `guild_permissions.manage_guild`) → **Admin**.

| Action | Member | Admin | Notes |
|---|---|---|---|
| All `/grocery` | ✅ | ✅ | Shared list |
| `/todo` on own personal tasks | ✅ | ✅ | |
| `/todo` on others' personal tasks | ❌ | ❌ | Not even Admins. Shows as "not found" |
| `/todo` on household tasks | ✅ | ✅ | Any member may edit/complete/delete (audited) |
| `/bill` on household bills | ✅ | ✅ | |
| `/bill` on own personal bills | ✅ | ✅ | |
| `/bill` on others' personal bills | ❌ | ❌ | |
| `/carl help`, `/carl settings`, `/carl export` | ✅ | ✅ | Export = household + own personal |
| `/carl setup`, `/carl summary`, `/carl status`, `/carl backup` | ❌ | ✅ | |
| Press **Mark paid** on household reminder | ✅ | ✅ | |
| Press **Mark paid** on personal DM reminder | owner only | owner only | |

## 4. `/grocery`

| Subcommand | Options (✱ = required) | Behavior |
|---|---|---|
| `add` | `item`✱ str ≤100 · `quantity` number 0.01–9999 · `unit` str ≤20 (autocomplete: lb, oz, kg, g, gal, l, ml, dozen, pack, bag, box, can, bottle, bunch, ct) · `category` choice (11 categories) · `note` str ≤300 | Adds or merges per FR-G-04. Category inferred if omitted. |
| `addmany` | `items`✱ str ≤1000, comma- or newline-separated, max 20 | Each entry parsed as `[qty] [unit] name`, e.g. `2 lb apples`, `milk`, `3 cans tomatoes`. Reply lists Added / Merged / Rejected per entry. |
| `list` | `view` choice: `needed` (default), `purchased`, `all` · `category` choice · `share` bool (**default true**) | Embed grouped by category. Shared (default): posted publicly in the current channel and becomes the **live list** (below). `share:false`: a private list that is not kept up to date. |
| `check` | `item`✱ autocomplete (needed items) | Mark purchased |
| `uncheck` | `item`✱ autocomplete (purchased items) | Back to needed; merges if a needed duplicate exists |
| `edit` | `item`✱ autocomplete (all) · `name` · `quantity` · `unit` · `category` · `note` · `clear` choice: `note`, `quantity`, `unit` | Only provided fields change. If the edit collides with another needed item's key → Conflict error suggesting removal. |
| `remove` | `item`✱ autocomplete (all) | Deletes one item immediately |
| `clear` | — | Confirmation: "Remove **7** purchased items? This can't be undone." [Clear 7 items] [Cancel] |

**Examples**
- `/grocery add item:oat milk quantity:2 unit:cartons` → "Added **oat milk** — 2 cartons (Dairy)."
- `/grocery addmany items:eggs, 2 lb apples, paper towels` → "Added 3: eggs (Dairy), apples 2 lb (Produce), paper towels (Household)."
- Adding `Apples 1 lbs` when `apples 2 lb` exists → "Merged with existing **apples**: now 3 lb."

**List view layout (≤ 25 items per page, grouped)**
```
🛒 Grocery list — 12 needed                     (embed title)
🥬 Produce
  • apples — 3 lb
  • spinach
🥛 Dairy
  • oat milk — 2 cartons  · note: unsweetened
…
Page 1/1 · Updated 2:14 PM                      (footer, local time)
[Select: ✔ Check off items… (multi, up to 25)]
[◀] [▶] [Show purchased (4)] [Clear purchased…] [↻]     (◀ ▶ appear only when there is more than one page)
```
Item lines show added-by only in `view:all` (`— added by @Name`) to keep the phone view short.

**Live list.** A list posted with `share:true` is remembered (channel id, message id, and its view/category in `app_state` key `grocery_live_list`). Whenever the list changes (add, addmany, check, uncheck, edit, remove, the tick-off menu, confirmed clear) Carl edits that message in place, **after** answering the user so the 3-second response limit is never at risk. Posting `/grocery list` again deletes the previous live message and replaces it, so there is only ever one; a private list (`share:false`) never replaces it. Clicking the live message itself updates it directly (no second edit). If the stored message is gone or can't be edited (404/403) it is forgotten with a logged warning; a temporary Discord error keeps it and logs a warning. None of this can make a user's command fail. A refresh re-renders the remembered view (page 1), so a user who toggled the live message to "purchased" sees it return to the remembered view when someone else changes the list.

**Short-lived replies.** Success replies for `add`, `addmany`, `check`, `uncheck`, `edit`, `remove` and the confirmed `clear` are small private (ephemeral) embeds that delete themselves after `BRIEF_SECONDS` (10 s, one constant in `responses.py`; must stay far below Discord's 15-minute interaction limit). Error replies, `addmany` replies that include rejected entries, the clear prompt, "Cancelled." and lists are not auto-deleted. Restarting the bot during the 10 seconds can leave one confirmation behind (harmless).

## 5. `/todo`

| Subcommand | Options | Behavior |
|---|---|---|
| `add` | `title`✱ ≤200 · `due` str (date expression, §7) · `priority` choice low/normal/high · `scope` choice personal (default)/household · `assignee` user (household only) · `repeat` choice none/daily/weekly/biweekly/monthly/monthly_last_day/quarterly/yearly · `repeat_every` int 1–12 · `notes` ≤1000 | Validation: `assignee` with `scope:personal` → error. `repeat` without `due` → error "Recurring tasks need a due date." Assignee must hold the household role. |
| `list` | `filter` choice: `mine` (default), `household`, `personal`, `today`, `soon`, `overdue`, `completed` | Sorted per FR-T-04. Overdue marked ⚠, due today marked •, priority high marked ‼. |
| `done` | `task`✱ autocomplete (open, visible) | Complete; if recurring, reply includes "Next: Mon Nov 9". |
| `reopen` | `task`✱ autocomplete (completed in last 30 days, visible) | Reopen |
| `postpone` | `task`✱ · `by` choice `1d`,`3d`,`1w`,`next_monday` · `to` date str | Exactly one of `by`/`to` required. Reply "Moved from Tue Nov 3 → Tue Nov 10." |
| `edit` | `task`✱ · `title` · `due` · `priority` · `scope` · `assignee` · `notes` · `clear` choice `due`,`assignee`,`notes`,`repeat` · `repeat` · `repeat_every` | Changing scope personal→household is allowed for the owner; household→personal only by the original owner, and it clears the assignee. |
| `delete` | `task`✱ | Confirm. Recurring: [Delete this one] [Delete & stop repeating] [Cancel] |

**List view**
```
✅ My tasks — 5 open
⚠ Renew car registration — due Mon Oct 19 (6 days overdue) ‼
• Call dentist — due today
  Take out trash — Mon Oct 26 · household · @Sam · 🔁 weekly
  Fix closet door — no due date
Page 1/1
[Select: ✔ Mark done… (multi)]  [◀] [▶] [Filter ▾ (select: mine/household/today/…)]
```

## 6. `/bill`

| Subcommand | Options | Behavior |
|---|---|---|
| `add` | `name`✱ ≤100 · `due`✱ date expression (first due date) · `amount` number 0–1,000,000,000 · `currency` str 3 letters (autocomplete supported list) · `repeat` choice (as todo, default none) · `repeat_every` int 1–12 · `remind` str e.g. `7,3,0` (0–5 values, each 0–60) · `scope` choice personal (default)/household · `notes` ≤1000 | Duplicate check (FR-B-06). Reply shows the next 3 due dates and the first reminder time. If `scope:household` and no reminder channel is set → saved, with warning "No reminder channel set — ask an admin to run /carl setup." |
| `list` | `scope` choice all (default)/personal/household · `archived` bool | Each bill: name, amount, repeat, next due, status ⚠ if overdue |
| `upcoming` | `days` int 1–60 (default 30) | Unpaid occurrences in range, grouped by week; includes delivery-warning marker (US-B7) |
| `overdue` | — | Unpaid occurrences with due_date < today |
| `paid` | `bill`✱ autocomplete (bills with unpaid occurrences) · `date` date expr (default today) · `amount` number · `note` ≤300 | Marks **earliest unpaid** occurrence paid. Reply: "Marked **Electric** (due Nov 1) paid. Next due Dec 1." |
| `unpaid` | `bill`✱ autocomplete (bills with a paid occurrence) | Reverts most recent paid occurrence to unpaid and re-plans its reminders. Already-sent reminders are not re-sent. |
| `skip` | `bill`✱ autocomplete | Marks earliest unpaid occurrence skipped (confirm button) |
| `history` | `bill` autocomplete (optional) · `limit` int 1–50 (default 12) | Paid and skipped occurrences, newest first |
| `edit` | `bill`✱ · `name` · `amount` · `currency` · `due` (next due date; re-anchors recurrence) · `repeat` · `repeat_every` · `remind` · `scope` · `notes` · `clear` choice `amount`,`notes`,`remind`(→default),`repeat` | Schedule fields trigger regeneration (database-design §7.4). Reply shows the new next due date and reminder times. |
| `delete` | `bill`✱ · `purge` bool (default false) | Confirm "Archive **Electric**? Reminders stop; history is kept." With `purge:true`: confirm text "Permanently delete **Electric** and **14** payment records?" and a red [Delete forever] button |

**Reminder message (channel or DM)**
```
🔔 Bill due in 3 days                      (embed title; "due today" / "is overdue" variants)
Electric — $84.20                          (description)
Due: Sun, Nov 1, 2026
Repeats: monthly
Notes: autopay off                         (household channel only shows notes if bill is household)
Delayed reminder (bot was offline)         (only when late)
ref N-1234                                 (footer: notification id, used for duplicate check)
[✔ Mark paid] [⏭ Skip this one]            (DynamicItems with occurrence id)
```
After Mark paid, the bot edits the original message: buttons removed, footer "Paid by @Alex · Oct 30".

**Summary message**
```
📅 Bills this week (Oct 26 – Nov 1)
⚠ Overdue: Water — $40.00 (due Oct 20)
• Tue Oct 27 — Internet — $60.00
• Sun Nov 1 — Electric — $84.20
Total due: $184.20 (USD)                   (one line per currency)
```

## 7. Date expressions (`due`, `to`, `date` options)

Parsed by `domain/dates.py`, relative to *today in the household zone*. Case-insensitive.

| Input | Meaning |
|---|---|
| `today`, `tomorrow` | |
| `mon` … `sun`, `monday` … `sunday` | Next occurrence, never today (`fri` on a Friday = next week) |
| `next week` | Next Monday |
| `+3d`, `+2w`, `+1m`, `in 3 days`, `in 2 weeks`, `in 1 month` | Relative; months clamp to month end |
| `2026-11-05` | ISO |
| `11/5`, `11/5/2026`, `11/5/26` | Month/day (MDY default). With `date_order=DMY` → day/month. Year omitted → next such date on or after today |
| `Nov 5`, `5 Nov`, `November 5 2026` | Month names (English) |

Invalid → ValidationError listing accepted formats. Dates more than 10 years out → error. Past dates are allowed for tasks and for bill `paid date`. For a new bill's first due date, past dates are allowed but the reply warns "This bill is already overdue."

The reply always echoes the interpreted date in an unambiguous form ("Sun, Nov 1, 2026") so mistakes are caught.

## 8. Component custom_id scheme (≤ 100 chars)

Format: `carl:v1:<domain>:<action>:<args…>`. Each pattern is a `DynamicItem` with a regex template.

| custom_id | Action |
|---|---|
| `carl:v1:gl:page:<view>:<cat\|_>:<page>` | Grocery list pagination / refresh |
| `carl:v1:gl:check` (select; values = item ids) | Bulk check |
| `carl:v1:gl:clearask` | Opens clear confirmation |
| `carl:v1:tl:page:<filter>:<page>` / `carl:v1:tl:done` (select) | Task list |
| `carl:v1:bl:paid:<occurrence_id>` / `carl:v1:bl:skip:<occurrence_id>` | Bill reminder buttons |
| `carl:v1:cf:<action>:<target_id>:<user_id>:<expires_epoch>:<yes\|no>` | Confirmation; handler rejects if presser ≠ `user_id` ("This confirmation belongs to someone else.") or now > expires ("This confirmation expired — run the command again.") |

Every component handler re-runs the authorization check and the record scope check. Lists re-query at click time, never trusting stale data embedded in the message.

## 9. Error and edge responses (all ephemeral)

| Situation | Message |
|---|---|
| Not a member / wrong guild | "You don't have access to Carl. Ask an admin for the household role." |
| Admin-only command | "Only Carl admins can do that." |
| Record not found or not visible | "That {item\|task\|bill} wasn't found. It may have been removed." |
| Validation error | "Couldn't save: {specific reason}." e.g. "Quantity must be between 0.01 and 9999." |
| Duplicate bill | "A {household\|personal} bill named **X** already exists. Use `/bill edit`." |
| Grocery edit collision | "There's already a needed **apples (lb)**. Remove one or change the unit." |
| Bad date | "I couldn't understand `{input}`. Try `tomorrow`, `fri`, `11/5`, `2026-11-05`, or `+3d`." |
| Unknown time zone | "`{tz}` isn't a known time zone. Start typing a city, e.g. `America/Chicago`." (autocomplete offers matches) |
| Reminder channel missing/inaccessible | "I can't post in {#channel}. Check that I have View Channel, Send Messages, and Embed Links there." |
| Expired / foreign confirmation | See §8 |
| Unexpected error | "Something went wrong (ref `E-7F3A`). It's been logged." |
| Discord rate-limited | Handled by discord.py retry; user sees nothing unless the 3 s deadline passes, in which case the handler has already deferred |

## 10. Limits and pagination

| Limit | Value |
|---|---|
| Items per list page | 20 lines (task/bill), 25 (grocery, matches select limit) |
| Select menu options | 25 (Discord max) — covers the current page |
| Embed description | ≤ 4096 chars; renderer truncates notes to 80 chars in lists |
| Autocomplete results | 25, filtered by case-insensitive substring of the typed text, open/needed first |
| Max open grocery items | 500 (soft guard; error beyond) |
| Max tasks per user (open) | 1000 soft guard |
| Max active bills per guild | 200 soft guard |

## 11. `/carl` (settings & ops)

| Subcommand | Who | Options | Behavior |
|---|---|---|---|
| `help` | Member | — | Short command overview with examples |
| `settings` | Member | — | Shows zone, reminder channel, reminder time, currency, default offsets, summary schedule, date order |
| `setup` | Admin | `channel` channel (text) · `timezone` str autocomplete · `reminder_time` `HH:MM` · `currency` · `default_remind` e.g. `3,0` · `date_order` MDY/DMY | Validates the bot can post in the channel (sends nothing; checks permissions). Re-plans pending notifications. Reply lists next 3 scheduled reminders (times only + bill names, ephemeral). |
| `summary` | Admin | `frequency`✱ off/daily/weekly · `weekday` choice Mon..Sun · `time` `HH:MM` | Saves and re-plans summaries |
| `status` | Admin | — | Version, uptime, gateway latency, last tick age, DB size, last backup, pending/failed notification counts, last 5 failed error codes (no content) |
| `export` | Member | — | Deferred ephemeral; attaches `carl-export-YYYYMMDD.json` (schema in `security-and-operations.md` §9) |
| `backup` | Admin | — | Runs online backup now; reports file name and size |

## 12. Requirement coverage

| FR | Command(s) |
|---|---|
| FR-G-01..11 | `/grocery add, addmany, list, check, uncheck, edit, remove, clear` + list components |
| FR-T-01..10 | `/todo add, list, done, reopen, postpone, edit, delete` + list components |
| FR-B-01..14 | `/bill add, list, upcoming, overdue, paid, unpaid, skip, history, edit, delete` + reminder buttons + `/carl summary` |
| FR-S-01..11 | registration scope, `auth.py`, `/carl *`, scheduler/backup |
