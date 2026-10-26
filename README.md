# Carl

A private Discord bot for one household: shared grocery list, to-dos, and bill reminders.
Design docs live in [docs/](docs/); implementation rules for contributors are in [CLAUDE.md](CLAUDE.md).

**Status:** Phases 1 and 2 are implemented: configuration, database and migrations,
time/date/recurrence libraries, household settings, the `/carl` commands, and the shared grocery
list (`/grocery`). To-dos and bill reminders arrive in later phases (see
[docs/implementation-plan.md](docs/implementation-plan.md)).

## Using the grocery list

- `/grocery add item:oat milk quantity:2 unit:cartons`: one item. Duplicates merge (adding apples
  twice sums the quantities; nothing is silently dropped).
- `/grocery addmany items:milk, 2 lb apples, 3 cans tomatoes`: up to 20 at once.
- `/grocery list`: your list by aisle, with a menu to tick items off and buttons to page,
  refresh, see purchased items, or clear them. Add `share:true` to post it for everyone.
- `/grocery check`, `uncheck`, `edit`, `remove`: pick the item from the suggestions or type its name.
- `/grocery clear`: removes checked-off items after you confirm.

## One-time Discord setup

Create **two** applications at <https://discord.com/developers/applications>: `Carl` (production)
and `Carl Dev` (what you use while developing). Never use the production token on your PC.

For each application:

1. **Bot** tab: click *Reset Token* and copy it (you only see it once). Turn **Public Bot off**.
   Leave all three *Privileged Gateway Intents* **off**; Carl doesn't need them.
2. **OAuth2 > URL Generator**: scopes `bot` and `applications.commands`. Bot permissions: View
   Channels, Send Messages, Embed Links, Read Message History, Attach Files. Open the generated URL
   to invite the bot to your server.

In your Discord server:

1. Turn on *Settings > Advanced > Developer Mode* in your Discord client.
2. Create a role called `household` and give it to everyone who may use Carl.
3. Right-click the server icon > *Copy Server ID*, and right-click the role (Server Settings >
   Roles) > *Copy Role ID*.
4. Create a text channel for reminders (for example `#bills`) visible only to the `household` role.

## Run it locally

Requires [uv](https://docs.astral.sh/uv/) (it also installs Python 3.12 for you).

```bash
uv sync                          # install dependencies
cp .env.example .env             # then fill in DISCORD_TOKEN (dev token), CARL_GUILD_ID,
                                 # CARL_HOUSEHOLD_ROLE_ID and CARL_DEFAULT_TIMEZONE
uv run python -m carl check-config
uv run python -m carl run
```

Then, in Discord, as a member with the `household` role:

- `/carl help`
- `/carl setup channel:#bills timezone:America/Chicago reminder_time:09:00` (admins only: members
  with the Manage Server permission, or the optional `CARL_ADMIN_ROLE_ID` role)
- `/carl settings`, `/carl status`

Slash commands appear within a few seconds of the first start. A member without the `household`
role gets "You don't have access to Carl."

## Develop

```bash
uv run pytest                    # all tests; offline, uses a fake clock
uv run pytest --cov=carl         # with coverage
uv run ruff check . && uv run ruff format --check .
uv run python -m carl migrate --status
uv run python -m carl backup     # online backup of data/carl.db into data/backups/
```

Exit codes: `0` ok, `2` bad configuration, `3` another instance is using the data directory,
`4` migration failure, `5` database integrity failure.

## Run in Docker

```bash
docker compose up --build        # data persists in ./data
```

## Data and secrets

All data is one SQLite file, `data/carl.db`, plus backups in `data/backups/`. `.env` and `data/`
are git-ignored. Never commit a token.
