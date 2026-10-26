# CLAUDE.md — Carl (household Discord bot)

You are implementing an **approved design**. Your job is to build it faithfully and incrementally, not to redesign it.

## Authoritative documents (read before coding)
| Topic | Document |
|---|---|
| What to build, acceptance criteria | `docs/requirements.md` |
| Order of work, file layout, per-phase tests | `docs/implementation-plan.md` ← **start here** |
| Components, layering, stack | `docs/architecture.md` |
| Schema (normative SQL), recurrence format, migrations | `docs/database-design.md` |
| Commands, options, messages, custom_ids | `docs/discord-commands.md` |
| Scheduling, DST, missed reminders, retries, recovery | `docs/reminder-system.md` |
| Secrets, logging, backups, deploy, restore | `docs/security-and-operations.md` |
| Why things are the way they are | `docs/architecture-decisions.md` |

Precedence on conflict: requirements (behavior) → reminder-system / database-design (mechanics) → others. If docs conflict or something needed is missing, **stop and ask the user**. Don't guess.

## Changes that need user approval first
- New runtime dependency (allowed: `discord.py~=2.7`, `aiosqlite`, `tzdata`, `python-dotenv`).
- New service or infrastructure (Redis, Postgres, web server, scheduler library, AI SDK).
- Schema changes beyond `0001_initial.sql` as specified, new command names or options, changed reminder semantics.
- Any change to an *Accepted* ADR. Update the docs in the same change once approved.

## Workflow
- Work **one phase at a time** (`implementation-plan.md` §2–§7). Finish its acceptance criteria, report results, and wait for approval before the next phase.
- Write tests first for `domain/` and `scheduler/` logic.
- Keep the app runnable at the end of every task.
- Commit only when the user asks.

## Conventions
- Python 3.12, `src/` layout, package `carl`. Format and lint with ruff (line length 100).
- **Layering:** `domain`, `services`, `repositories`, `scheduler`, `db` must not import `discord` (a test enforces it). Discord code lives only in `src/carl/discord_ui/`.
- **Time:** never call `datetime.now()`/`date.today()`/`time.time()`; use the injected `Clock`. Store instants as UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`, due dates as local `YYYY-MM-DD`. Conversions only in `domain/timeutil.py` (`fold=0`).
- **SQL:** only in `repositories/` and `db/`, parameterized, every query scoped by `guild_id`. Task and bill queries also apply the visibility predicate. Writes go inside `db.transaction()`.
- **Money:** integer minor units + ISO currency; parse with `Decimal`.
- **Errors:** raise `CarlError` subclasses in services; `discord_ui/errors.py` maps them to messages from `discord-commands.md` §9.
- **Privacy:** replies ephemeral by default; `allowed_mentions=none`; never log names, titles, amounts, notes, or user-typed values (IDs and event names only).
- **Components:** `DynamicItem` with `carl:v1:…` custom_ids; re-check authorization and scope on every click. Hard-won rules (each one was a real bug in Phase 2):
  - Wrap every callback in `components.base.guard(...)`. discord.py does not run the command tree's access check or our error handling for component clicks.
  - Call `view.stop()` on every View you send (see `components.grocery.finish`). A live view *and* a registered DynamicItem would both handle one click.
  - Never name an attribute `view` on an Item (it's a read-only discord.py property). Use `list_view` etc.
  - Autocomplete skips the command tree's access check: call `components.base.autocomplete_actor` and return `[]` for non-members.
  - `app_commands.Range` bounds must be the same type (`Range[float, 0.01, 9999.0]`, not `9999`).
  - Reply with `responses.respond` (ephemeral, `allowed_mentions=none`) and wrap user text in `responses.safe`.
- **Live grocery list:** any code path that changes grocery data must, *after answering the user*, call `client.live_list.refresh_after(interaction)` (it never raises). Success replies use `responses.respond_brief` (self-deleting); errors use `respond`.
- **Database writes** go through `db.transaction()`, which queues concurrent callers; never write outside it from code that can run alongside commands.
- **Logging:** `aiosqlite` logs SQL *values* at DEBUG; `logging_setup.quiet_noisy_loggers` keeps it at WARNING. Don't undo that.
- **Tests must never start the real bot or read a real `.env`** (the CLI only reads `./.env` from the current directory; `tests/integration/test_cli.py` patches `_run_bot` to fail if called).

## Commands
```bash
uv sync                          # install (dev deps included)
uv run pytest                    # all tests (offline, fake clock/notifier)
uv run pytest --cov=carl         # coverage (domain/services target ≥ 90%)
uv run ruff check . && uv run ruff format --check .
uv run python -m carl check-config
uv run python -m carl migrate [--status]
uv run python -m carl run        # needs .env with a DEV bot token
docker compose up --build        # containerized run, data in ./data
```

## Migrations
- New file `src/carl/db/migrations/NNNN_name.sql` (next number, 4 digits). **Never edit or delete an applied migration**; fix forward.
- Migrations auto-apply at startup after an automatic pre-migration backup. A checksum mismatch refuses startup.
- Update `tests/fixtures/schema_snapshot.sql` in the same change, and update `docs/database-design.md`.

## Never
- Use the production token locally, commit `.env`, or print secrets.
- Enable privileged intents (message content, members, presences).
- Add payment, banking, or credential storage features.
- Make core features depend on an AI or paid API.
- Promise or implement "exactly-once" delivery; follow `reminder-system.md`.
- Install dependencies globally, deploy, or touch cloud resources unless the user asks.
