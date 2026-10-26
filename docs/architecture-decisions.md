# Carl — Architecture Decision Records

Status: **Approved design baseline v1.0** (2026-10-25). Changing an *Accepted* ADR requires the user's approval and a new superseding ADR.

---

## ADR-001 Language and Discord library: Python 3.12 + discord.py 2.7
**Status:** Accepted

**Context:** Beginner-friendly maintenance, low memory on small hosts, solid time-zone handling, full slash-command and component support. The user prefers Python.

| Criterion | Python + discord.py | TypeScript + discord.js |
|---|---|---|
| Readability for a beginner | ✅ simpler syntax, no build step | Type system helps, but needs a tsconfig, build, and more tooling |
| Memory footprint | ✅ ~60–120 MB ⚪ | Node + discord.js typically higher ⚪ |
| Time zones | ✅ stdlib `zoneinfo` | Needs Luxon/Temporal polyfill |
| Slash commands / components | ✅ `app_commands`, `DynamicItem` persistent components | ✅ equally capable |
| Ecosystem / docs | Good; smaller than discord.js | Largest Discord ecosystem |
| Maintenance status | ✅ active (2.7.1, 2026-03-03) | Active |
| SQLite | ✅ stdlib `sqlite3` | `better-sqlite3` native module (arm builds) |

**Decision:** Python 3.12 with `discord.py ~= 2.7`.
**Consequences:** asyncio throughout; use `aiosqlite` to avoid blocking the loop; pin discord.py's minor version.

## ADR-002 Database: SQLite (WAL) with raw SQL and a tiny migration runner
**Status:** Accepted

**Alternatives:** Postgres (needs another service and more RAM; free hosted Postgres tiers expire, e.g. Render's 30-day limit); JSON files (no constraints or transactions; corruption-prone); SQLAlchemy + Alembic (a powerful but large abstraction for ~9 tables).

**Decision:** SQLite with `STRICT` tables, CHECK constraints, partial unique indexes, WAL, `synchronous=FULL`. Raw parameterized SQL in repositories. Numbered `.sql` migrations with checksums.
**Consequences:** single writer, which suits one process; one file to back up (online backup API); the schema is readable in one file. A Postgres move later would mean rewriting repositories only.

## ADR-003 Scheduling: DB-backed outbox polled by an in-process loop
**Status:** Accepted

**Alternatives:**
- *APScheduler* with SQLAlchemy job store: adds dependencies, hides state in pickled jobs, and its misfire handling doesn't capture our "send only the latest missed reminder" rule.
- *discord.ext.tasks* timers per reminder: in-memory, lost on restart.
- *OS cron* invoking a script: needs a second entry point and a token login per run; awkward with a running gateway bot.

**Decision:** `notifications` table with dedupe keys, statuses, and attempts. A 30-second asyncio loop plans, dispatches, recovers, and maintains (`reminder-system.md`).
**Consequences:** All reminder state is queryable SQL that survives restarts and can be tested with a fake clock. We own ~300–400 lines of careful code (Phase 4 is the hardest).

## ADR-004 Runtime model: long-running Gateway bot (not serverless HTTP interactions)
**Status:** Accepted

**Alternatives:** Discord HTTP interactions endpoint on Cloudflare Workers + Cron Triggers + D1. ✅ Free plan: 10 ms CPU/invocation, 5 cron triggers/account. No server to manage.

**Decision:** Gateway bot as one process.
**Why:** works with discord.py; needs no public HTTPS endpoint or signature verification; the reminder engine stays in our code instead of a vendor's cron; the same container moves between GCP, Pi, and VPS. The serverless route would need JS/TS (or experimental Python Workers), vendor-specific storage, and a rewrite to leave.
**Consequences:** requires an always-on host (ADR-005).

## ADR-005 Hosting: Google Cloud e2-micro Always Free first; Raspberry Pi and paid VPS as portable alternatives
**Status:** Accepted (re-verify terms at sign-up)

**Evidence:** `hosting-comparison.md`. GCP's free e2-micro is an always-on VM with a 30 GB standard disk and no documented idle reclamation. Oracle's Always Free documents idle reclamation that an idle bot would trigger. Render and Koyeb free tiers sleep. Fly.io and Railway have no ongoing free tier for new users. AWS's new free plan ends after 6 months.

**Decision:** GCP e2-micro in a free-tier US region with a $1 budget alert; Pi (with Pi-hole coexistence) when the user owns one; ~$5/mo VPS as the paid fallback.
**Consequences:** credit card on file; must stay inside free-tier resource types; off-host backups required.

## ADR-006 Containerization: Docker Compose, single service, multi-arch image; systemd as no-Docker fallback
**Status:** Accepted

**Alternatives:** bare venv + systemd only (lighter, but less uniform across hosts); Kubernetes/k3s (absurd at this scale).
**Decision:** `compose.yaml` with restart policy, healthcheck, non-root, read-only rootfs, resource limits, log rotation. A `deploy/carl.service` is provided for no-Docker hosts.
**Consequences:** ~50–100 MB Docker daemon overhead ⚪ on a 1 GB VM. Acceptable with swap.

## ADR-007 Interaction model: slash commands + persistent components; no message-content or members intents
**Status:** Accepted

**Decision:** Four command groups; autocomplete for record selection; `DynamicItem` components with self-describing custom_ids; ephemeral by default; `Intents.none() + guilds`.
**Why:** Discord recommends slash commands; privileged intents are unnecessary because interactions include the member's roles; this keeps a private bot's data exposure minimal.
**Consequences:** no "type 'add milk' in chat" convenience. `/grocery addmany` and autocomplete close most of the gap.

## ADR-008 Authorization: one guild + household role; admin by role or Manage Server
**Status:** Accepted

**Alternatives:** user-ID allowlist in env (needs a redeploy to add someone); per-command Discord permission overrides (configured in the Discord UI; easy to misconfigure and invisible to the code).
**Decision:** runtime check on every interaction against `CARL_GUILD_ID` and `CARL_HOUSEHOLD_ROLE_ID` (+ optional admin role).
**Consequences:** adding a member = giving them a role in Discord.

## ADR-009 Time model: local calendar dates for due dates; UTC instants for scheduling; one household zone
**Status:** Accepted

**Decision:** `due_date` is a local date; reminder instants are computed with `zoneinfo`, `fold=0`; recurrence is computed from the anchor with month-end clamping.
**Consequences:** DST can't move a due date; reminder times are predictable; per-user zones come later via a migration (target resolution is already per-notification).

## ADR-010 Delivery semantics: at-least-once with lookup-before-resend
**Status:** Accepted

**Decision:** Claim → send → record. Recovery and retries first look for the `ref N-{id}` footer in recent history. Missed reminders collapse to the latest one; expiry windows bound retries.
**Consequences:** needs Read Message History permission in the reminder channel. Rare duplicates remain possible and are documented.

## ADR-011 No AI in core
**Status:** Accepted

**Decision:** All parsing (dates, add-many, categories) is deterministic code with tables. Any future AI feature (e.g. free-text "remind me…") must be a separate optional module behind a config flag. Core never imports it and works when it's disabled.

## ADR-012 Packaging: uv + pyproject.toml + lockfile
**Status:** Accepted

**Alternatives:** pip + requirements.txt (familiar, but no lockfile by default); Poetry (heavier).
**Decision:** `uv` for reproducible installs (`uv.lock`) and fast container builds; `pip install .` still works for anyone without uv.
