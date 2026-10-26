# Carl — Security & Operations

Status: **Approved design baseline v1.0** (2026-10-25)
Audience: the Operator (you) and the implementer. Commands assume a Debian-family Linux host with Docker Compose v2.

---

## 1. Threat model

**Assets:** bill names, amounts, and due dates; personal tasks; household schedule; the Discord bot token; backups.
**Trust boundary:** Members are trusted not to be malicious toward each other's *shared* data, but personal data stays private between Members. The host operator can read everything (they hold the database).

| # | Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| T1 | Bot token leaked (committed to git, pasted in a log or chat) | Medium | High: attacker acts as the bot and reads the channels it can see | Token only in `.env` (mode 600, git-ignored); never logged; `check-config` prints only the last 4 chars; rotation procedure §3.3; GitHub secret scanning if the repo is hosted there |
| T2 | Non-household server member uses commands | Medium | Medium | Role check on every interaction and component (§2) |
| T3 | Member reads/edits another's personal task or bill by forging an autocomplete value or button ID | Low | Medium | Every query includes the visibility predicate; IDs are never trusted alone; not-found response doesn't reveal existence |
| T4 | Bot invited to a foreign server | Low | Low | Public Bot off; auto-leave foreign guilds; commands registered only in the home guild |
| T5 | Personal reminder leaks into shared channel | Low | Medium | No DM→channel fallback; household notes shown only for household bills |
| T6 | Sensitive data in logs | Medium | Medium | Redaction policy §5 + automated test |
| T7 | Backup file stolen from off-host location | Low | High | Off-host copies encrypted with `age` (§7.3); on-host files mode 600 |
| T8 | Host compromise (SSH brute force, unpatched OS) | Low | High | No inbound ports except SSH (key-only or IAP/Tailscale); unattended security upgrades; container runs non-root, read-only rootfs, no capabilities |
| T9 | Database corruption / failed writes | Low | High | WAL + `synchronous=FULL`; transactions; `quick_check` at startup; verified daily backups; restore drill |
| T10 | Duplicate instance spamming reminders | Low | Low | Lock file; separate dev application |
| T11 | Malicious/oversized input (huge strings, markdown/mention injection) | Medium | Low | Length limits; `allowed_mentions=none` on all messages; escape markdown in user text inside embeds |
| T12 | Supply-chain compromise of a dependency | Low | High | 4 runtime deps; `uv.lock` with hashes; update deliberately |
| T13 | Users storing account numbers in notes | Medium | Medium | Notes field hint text; docs; no payment features at all |

Out of scope: Discord itself reading messages (inherent to using Discord), a malicious host operator.

## 2. Authorization and data scoping

1. Interactions from guilds other than `CARL_GUILD_ID` → rejected (and the bot leaves the guild).
2. `require_member(interaction)` checks the roles on `interaction.user` (a `discord.Member`, with roles provided in the interaction payload). This needs no members intent. It returns an `Actor(guild_id, user_id, is_admin)`.
3. Services receive the `Actor`, never raw Discord objects. Every repository method takes `guild_id`. Task and bill lookups also take `viewer_user_id` and apply `scope = 'household' OR owner_user_id = viewer`.
4. Component clicks re-run steps 1–3. Confirmation IDs embed the invoking user ID and an expiry.
5. All outgoing messages use `allowed_mentions = AllowedMentions.none()`, except the explicit user mention for an assignee in a household context, which uses `users=[that user]`.
6. Audit log records actor, action, entity type/id, and changed field names. It never records values of names, notes, or amounts.

## 3. Secrets and configuration

### 3.1 Environment variables (`.env`, see `.env.example`)

| Variable | Required | Secret | Example |
|---|---|---|---|
| `DISCORD_TOKEN` | ✅ | ✅ | — |
| `CARL_GUILD_ID` | ✅ | | `123456789012345678` |
| `CARL_HOUSEHOLD_ROLE_ID` | ✅ | | `234567890123456789` |
| `CARL_ADMIN_ROLE_ID` | | | `345678901234567890` |
| `CARL_DEFAULT_TIMEZONE` | ✅ | | `America/Chicago` |
| `CARL_DEFAULT_CURRENCY` | | | `USD` |
| `CARL_DATE_ORDER` | | | `MDY` |
| `CARL_DATA_DIR` | | | `./data` (dev) / `/data` (container) |
| `CARL_BACKUP_TIME` | | | `03:30` |
| `CARL_LOG_LEVEL` | | | `INFO` |
| `CARL_HEALTHCHECK_URL` | | ✅ (contains a token) | `https://hc-ping.com/<uuid>` |
| `CARL_ENV` | | | `dev` or `prod` |

`DISCORD_TOKEN` and `CARL_HEALTHCHECK_URL` are held in a `SecretStr` wrapper whose `repr` and `str` print `****abcd`.

### 3.2 Rules
- `.env` is git-ignored and `.dockerignore`d; only `.env.example` is committed. On the host: `chmod 600 .env`.
- **Two Discord applications:** "Carl" (prod) and "Carl Dev" (dev), each with its own token. Dev uses a test server or a test channel, and its own `data/`. Never run the prod token on your PC.
- No secrets in the image, compose file, or command-line arguments.

### 3.3 Token rotation
Developer Portal → Bot → Reset Token → update `.env` on host → `docker compose up -d` (recreates the container). The old token is invalid immediately. Do this after any suspected leak.

## 4. Input validation

All validation lives in `domain/` (pure, unit-tested) and runs before any DB write:
- Strings: strip, NFKC, reject control characters except newline in notes, enforce lengths (`database-design.md` §4 CHECKs mirror them).
- Numbers: Discord enforces option min/max; services re-check. Amount input is parsed as `Decimal` and converted with the currency exponent (reject excess precision, e.g. `$1.234`).
- Dates: `domain/dates.py` grammar only; range ±10 years.
- Time zone: must be in `zoneinfo.available_timezones()`.
- Offsets: `^\s*\d{1,2}(\s*,\s*\d{1,2}){0,4}\s*$`, each ≤ 60.
- IDs from autocomplete or custom_id: integer parse, then scoped lookup.
- SQL: parameterized only; no string formatting into SQL (lint rule + review).
- Rendering: user text in embeds goes through `discord.utils.escape_markdown` and `escape_mentions`.

## 5. Logging

- Format (stdout): `2026-10-29T14:00:01.123Z INFO carl.dispatch event=notification_sent id=1234 kind=bill_reminder attempt=1 latency_ms=180`
- **Allowed in logs:** event names, record IDs, guild/user/channel IDs, command names, option *names*, counts, durations, error codes, exception types and stack traces.
- **Never in logs:** item names, task titles, bill names, amounts, notes, option *values* from users, message content, tokens, healthcheck URL.
- Implementation: services log IDs only. A `RedactingFilter` on the root logger masks anything matching the token pattern as a backstop. A test runs a full command flow with a sentinel string (e.g. `SENTINEL_9f2b`) as the item name and asserts it never appears in captured logs.
- discord.py's own logger is set to `WARNING` (`INFO` in dev).
- Rotation: Docker `json-file`, `max-size=10m`, `max-file=3` (≤ 30 MB). Under systemd: journald defaults.

## 6. Data integrity

- Every service method runs in one `BEGIN IMMEDIATE … COMMIT`. Exceptions → `ROLLBACK`, then a typed error to the user.
- Startup: `PRAGMA quick_check`. If it fails → log CRITICAL, refuse to start (exit code 5) with the message "Database integrity check failed — see Restore procedure (docs/security-and-operations.md §8)." Starting on a corrupt DB could make things worse.
- Disk full / I/O error during write → transaction rolls back; user sees the generic error with ref ID; `/carl status` shows the last DB error.
- Daily backup runs `PRAGMA integrity_check` on the **copy**. Failure → keep previous backups, set `app_state.last_backup_error`, log ERROR.

## 7. Backups

### 7.1 Automatic on-host backups
- Daily at `CARL_BACKUP_TIME` (household local time, default 03:30), using SQLite's online backup API (`sqlite3.Connection.backup`). This is safe while the bot runs.
- Layout: `data/backups/daily/carl-YYYYMMDD.db` (keep 14), `data/backups/weekly/carl-YYYY-Www.db` (Sunday's copy, keep 8), `data/backups/pre-migration-NNNN-<UTC>.db` (keep 5).
- Files are created with mode 600 (process umask 077).
- `/carl backup` and `python -m carl backup` run the same routine on demand.

### 7.2 Off-host copy (strongly recommended)
An on-host backup doesn't help if the VM or SD card dies. Choose one:
- **Pull to your Windows PC weekly** (simplest): Task Scheduler runs `scp <host>:/opt/carl/data/backups/weekly/* D:\CarlBackups\`. The PC's disk is the second copy. Encrypt the folder (BitLocker) or use `age` as below.
- **Push encrypted to cloud storage**: host cron runs `age -r <your-public-key> -o carl-<date>.db.age <file>`, then uploads with `rclone` to a personal cloud drive. Keep the `age` private key off the host, e.g. in a password manager.

### 7.3 Encryption
Off-host copies must be encrypted (`age`, or an encrypted disk). On-host copies rely on host access control.

## 8. Restore procedure (tested in Phase 5)

```bash
cd /opt/carl
docker compose stop carl                                   # 1. stop the bot (releases lock)
mkdir -p data/quarantine/$(date -u +%Y%m%dT%H%M%SZ)
mv data/carl.db* data/quarantine/<that-dir>/               # 2. keep the bad/current DB (incl. -wal, -shm)
docker compose run --rm carl python -m carl restore --check /data/backups/daily/carl-20261101.db
                                                           # 3. integrity_check + schema version ≤ code
docker compose run --rm carl python -m carl restore /data/backups/daily/carl-20261101.db
                                                           # 4. copy into place, mark past-due pending rows 'restored'
docker compose up -d                                       # 5. start; migrations apply if backup is older
docker compose logs -f carl                                # 6. confirm "ready", then run /carl status
```

`carl restore`:
- Refuses to run if the lock file is held by a live process.
- Copies the backup using the backup API, not a raw file copy.
- Sets `status_reason='restored'` on `pending`/`sending` notifications with `scheduled_for ≤ now`, and resets `sending` → `pending`. The dispatcher then checks Discord history for each before sending (`reminder-system.md` §7 step 6), so reminders already delivered after the backup was taken are not sent again.
- Writes an audit entry `system.restore`.

Data entered after the backup's timestamp is lost. That is the cost of daily backups; run `/carl backup` before risky operations.

**Restore drill:** quarterly, restore the latest backup into a scratch directory on any machine and run `python -m carl restore --check`.

## 9. Export format (`/carl export`)

```json
{
  "format": "carl-export", "version": 1,
  "exported_at": "2026-11-01T15:00:00.000Z",
  "guild_id": 123, "requested_by": 456, "timezone": "America/Chicago",
  "grocery_items": [ { "id": 1, "name": "apples", "quantity": 3, "unit": "lb", "category": "produce", "note": null, "status": "needed", "added_by_user_id": 456, "created_at": "…" } ],
  "tasks": [ { "id": 7, "scope": "household", "title": "…", "due_date": "2026-11-02", "status": "open", "recurrence": { "v": 1, "freq": "weekly", "interval": 1, "anchor": "2026-11-02" }, "…": "…" } ],
  "bills": [ { "id": 3, "scope": "household", "name": "Electric", "amount": "84.20", "currency": "USD", "recurrence": { "…": "…" }, "reminder_offsets": [3, 0], "archived": false,
               "occurrences": [ { "due_date": "2026-11-01", "status": "paid", "paid_on_date": "2026-10-30", "paid_amount": "84.20" } ] } ]
}
```
Includes household data plus the requester's personal tasks and bills. Excludes notifications, audit log, and other members' personal data. Amounts are decimal strings. Import is a later feature.

## 10. Deployment

### 10.1 Repository files the implementation provides
- `Dockerfile`: `python:3.12-slim` base. Install `uv`, then `uv sync --frozen --no-dev`. Create user `carl` uid 10001. `WORKDIR /app`. `ENV CARL_DATA_DIR=/data PYTHONUNBUFFERED=1`. `USER 10001`. `ENTRYPOINT ["python","-m","carl"]`, `CMD ["run"]`. Multi-stage so build tools don't ship.
- `compose.yaml`:

```yaml
services:
  carl:
    build: .
    image: carl:local
    container_name: carl
    restart: unless-stopped
    env_file: .env
    environment:
      CARL_DATA_DIR: /data
    volumes:
      - ./data:/data
    user: "10001:10001"
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    mem_limit: 256m
    cpus: 0.5
    stop_grace_period: 30s
    healthcheck:
      test: ["CMD", "python", "-m", "carl", "healthcheck"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 90s
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "3" }
```

- `compose.pi.yaml` (override, used on the Raspberry Pi): adds `dns: ["1.1.1.1", "9.9.9.9"]`. Usage: `docker compose -f compose.yaml -f compose.pi.yaml up -d`.
- `deploy/carl.service`: systemd unit for running without Docker (venv at `/opt/carl/.venv`, `User=carl`, `Restart=always`, `After=network-online.target time-sync.target`).

### 10.2 Google Cloud e2-micro (primary host)

1. Create a Google Cloud account and billing account. **Set a budget alert at $1/month** (Billing → Budgets & alerts) so any accidental charge is noticed quickly.
2. Compute Engine → Create instance:
   - Region `us-central1`, `us-east1`, or `us-west1` (free-tier regions only).
   - Machine type **e2-micro**. Not preemptible/Spot.
   - Boot disk: Debian (current stable), **Standard persistent disk**, **30 GB or less**. Not "balanced" or SSD, which are not free.
   - Firewall: leave HTTP/HTTPS unchecked. Keep the default ephemeral external IP, which is needed for outbound internet without paid Cloud NAT.
3. SSH in (browser SSH button). Add 1 GB swap:
   `sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab`
4. Security updates: `sudo apt install -y unattended-upgrades`.
5. Install Docker Engine + Compose plugin (Docker's official Debian instructions). `sudo systemctl enable --now docker`.
6. Get the code: private GitHub repo with a read-only deploy key → `sudo git clone … /opt/carl`. Alternatively, `scp` a release tarball.
7. `cd /opt/carl && cp .env.example .env && nano .env && chmod 600 .env`.
8. `mkdir -p data && sudo chown -R 10001:10001 data`.
9. `docker compose up -d --build` → `docker compose logs -f` until you see `event=ready`.
10. In Discord: `/carl setup channel:#bills timezone:America/Chicago`, then `/carl status`.
11. After one week: check Billing → Reports shows $0.00. Watch network egress; 1 GB/month North America egress is free.

### 10.3 Update procedure
```bash
cd /opt/carl && git pull
docker compose run --rm carl python -m carl backup     # belt and braces before migrations
docker compose up -d --build
docker compose logs --tail=50 carl
```
Rollback: `git checkout <previous tag>` + `docker compose up -d --build`. If a migration ran, restore the `pre-migration` backup first (§8). The previous code cannot read a newer schema.

### 10.4 Raspberry Pi with Pi-hole (alternative host)

**Separation principle:** Pi-hole and Carl are separate applications that only share hardware. Carl never touches Pi-hole's config, ports, or data, and works when Pi-hole is stopped.

| Topic | Guidance |
|---|---|
| Hardware | Pi 4 or Pi 5 with 2 GB is comfortable. Pi 5 1 GB works: Pi-hole ~100 MB + Carl ≤ 150 MB + OS. Prefer a USB SSD; else a high-endurance microSD card. Official power supply. |
| OS | Raspberry Pi OS Lite **64-bit** (arm64 image). |
| Processes | Pi-hole installed per its official method (native installer or its own compose project). Carl in **its own** compose project at `/opt/carl`. Separate data directories, separate update cycles. |
| Ports | Pi-hole binds 53/udp+tcp and its web UI port. **Carl binds no ports.** No conflict is possible. |
| CPU/RAM isolation | `mem_limit: 256m`, `cpus: 0.5` on Carl so it can never starve DNS. Pi-hole gets no limit. |
| DNS for Carl | `compose.pi.yaml` sets public resolvers for the Carl container, so Carl keeps working if Pi-hole is down or misconfigured, and Pi-hole blocklists can never block Discord domains for Carl. |
| DNS for the Pi host | Static LAN IP via router DHCP reservation. Give the host a public fallback resolver so NTP and apt work while Pi-hole is starting or broken. |
| Time | `sudo systemctl enable systemd-time-wait-sync`. Docker starts after `time-sync.target` (drop-in override). Carl's clock-sanity guard is the backstop. |
| Restart | `systemctl enable docker`; Carl `restart: unless-stopped`; Pi-hole per its installer (systemd or its own restart policy). |
| Logs | Docker log rotation (above); Pi-hole's own log settings. Optionally `log2ram` to reduce SD writes. |
| Backups | Same as §7. Off-host copy matters more on SD cards. |
| Remote access | No router port-forwarding. Use Tailscale (or WireGuard) for SSH from outside the home. SSH keys only, password login disabled. Never expose the Pi-hole admin UI to the internet. |
| Power outage | Committed data survives (WAL + FULL sync). On boot: time sync → Docker → Carl → missed-reminder policy. Small UPS optional. |
| Internet outage | Pi-hole continues serving cached/local DNS. Carl retries Discord with backoff; reminders follow `reminder-system.md` §11. |
| Discord outage | Same as internet outage from Carl's view. Pi-hole unaffected. |

### 10.5 Moving between hosts
1. Old host: `/carl backup`, then `docker compose stop carl`.
2. Copy `data/carl.db` (after stopping, so the WAL is checkpointed; or the latest backup file) and `.env` to the new host.
3. New host: steps 5–9 of §10.2 (or Pi equivalent), placing the file at `data/carl.db`.
4. Start. Only after the new host shows `ready`, delete the old VM or disable its container. **Never run both.**

## 11. Monitoring

| Signal | Where | Action |
|---|---|---|
| Container health | `docker ps` (healthy/unhealthy); Docker restarts on crash | |
| Heartbeat | `data/heartbeat` updated every tick; `python -m carl healthcheck` fails if older than 120 s | Docker marks unhealthy |
| External dead-man switch (optional) | Every 5 min the scheduler GETs `CARL_HEALTHCHECK_URL` (e.g. a Healthchecks.io check, free hobby tier at time of writing; verify) | Service emails you if pings stop for 15 min |
| `/carl status` | Discord | Pending/failed counts, last backup, last error codes |
| Logs | `docker compose logs --since 1h carl` | |

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Container exits with code 2 | Missing/invalid env var | `docker compose run --rm carl python -m carl check-config` |
| Exit code 3 | Another instance holds the lock | Stop the other container/process; check `data/carl.lock` PID |
| Exit code 4 | Migration failed or edited migration | Read the log; restore the pre-migration backup; fix forward |
| Exit code 5 | DB integrity failure | Restore (§8) |
| Slash commands don't appear | Not synced to guild, wrong `CARL_GUILD_ID`, or bot invited without `applications.commands` | Check logs for `commands_synced`; re-invite with both scopes |
| "You don't have access to Carl" | Missing household role or wrong role ID | Give the role; check `CARL_HOUSEHOLD_ROLE_ID` |
| "Application did not respond" | Bot down/reconnecting, or a handler exceeded 3 s without deferring | `docker compose ps`/logs; handler bug → defer |
| Household reminders not arriving | Channel unset, or bot lacks permissions | `/carl status` shows `no_channel` / `missing_permissions`; fix permissions; pending rows retry automatically until expiry |
| Personal reminder never arrives | User blocks DMs from server members | User enables Server Privacy → Direct Messages; status shows `dm_forbidden` |
| Reminders an hour off | Wrong household time zone | `/carl setup timezone:…` (re-plans automatically) |
| Unhealthy after Pi reboot | Clock not synced (`clock_insane` in logs) | Check `timedatectl`; enable time-wait-sync |
| GCP bill > $0 | Disk type not standard, > 30 GB, non-free region, or egress > 1 GB | Billing reports → SKU; fix the resource |
| Oracle instance stopped | Idle reclamation (if using Oracle) | See `hosting-comparison.md` §3.2 |
