# HN Daily

A lightweight Python script that scrapes the [Hacker News](https://news.ycombinator.com) front page each day, picks the top stories matching your interests, summarises each one with a local LLM, and delivers them to you via Telegram.

## What it does

1. Fetches the HN front page
2. Scores stories against configurable interest keywords (AI, cybersecurity, ethics, philosophy by default)
3. Skips any story already sent in a previous run (dedupe)
4. Picks the top 5 new matches
5. Downloads and cleans each article
6. Summarises each article using a local LLM via [lemonade-server](https://github.com/lemonade-sdk/lemonade) (OpenAI-compatible API)
7. Sends one Telegram message per story with summary + key takeaways + links
8. Records each sent story in a local SQLite datastore

## Requirements

- [uv](https://docs.astral.sh/uv/) — manages the Python 3.10+ runtime and dependencies for you
- A running [lemonade-server](https://github.com/lemonade-sdk/lemonade) instance (local LLM — tested with `Gemma-3-4b-it-GGUF`)
- A [Telegram bot token](https://core.telegram.org/bots#how-do-i-create-a-bot)
- Your Telegram numeric chat ID

## Installation

```bash
git clone https://github.com/rarmknecht/hndaily.git
cd hndaily
uv sync
```

`uv sync` creates an isolated virtual environment and installs the pinned dependencies from `uv.lock`. Nothing is installed into your system Python.

## Configuration

Set the following environment variables (or put them in a `.env` file in the project directory):

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | ✅ | — | Telegram bot token from @BotFather |
| `OWNER_ID` | ✅ | — | Your Telegram numeric chat ID |
| `LEMONADE_URL` | ❌ | `http://localhost:8000/v1` | Base URL for your lemonade-server instance |
| `LEMONADE_MODEL` | ❌ | `Gemma-3-4b-it-GGUF` | Model name to use for summarisation |
| `HNDAILY_DB` | ❌ | `hndaily.db` (next to the script) | Path to the SQLite datastore file |
| `LOG_LEVEL` | ❌ | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

Example `.env`:

```env
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
OWNER_ID=987654321
LEMONADE_URL=http://localhost:8000/v1
LEMONADE_MODEL=Gemma-3-4b-it-GGUF
```

## Usage

```bash
uv run hn_daily.py
```

`uv run` syncs the environment automatically before running, so there is no separate activation step.

### Run on a schedule (cron)

To receive your daily digest automatically, add a cron job:

```bash
# Run every morning at 7 AM
0 7 * * * cd /path/to/hndaily && uv run hn_daily.py >> hn_daily.log 2>&1
```

Use the full path to `uv` if cron runs with a minimal `PATH` (e.g. `~/.local/bin/uv` or the output of `which uv`).

## Customising interests

Edit the `INTEREST_KEYWORDS` dict in `hn_daily.py` to tune which stories get picked. Each keyword maps to a score weight — higher weight = stronger preference.

## Datastore

Every story sent to Telegram is recorded in a local SQLite database (`hndaily.db` by default). This serves two purposes:

- **Dedupe** — a story is identified by its Hacker News item id; once recorded it is never sent again.
- **Independent querying** — the file is plain SQLite, so any other app can read the digest history directly with SQL.

The `stories` table holds: `hn_id`, `title`, `article_url`, `hn_url`, `score`, `summary`, `key_points` (JSON array), `article_text` (cleaned article body), and `sent_at` (ISO 8601 UTC).

Example queries:

```bash
# The 10 most recent stories sent
sqlite3 hndaily.db "SELECT sent_at, title FROM stories ORDER BY sent_at DESC LIMIT 10;"

# Full record for one story
sqlite3 hndaily.db "SELECT summary, key_points FROM stories WHERE hn_id = '12345678';"
```

The datastore is created automatically on first run.

## License

MIT — see [LICENSE](LICENSE)
