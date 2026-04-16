# HN Daily

A lightweight Python script that scrapes the [Hacker News](https://news.ycombinator.com) front page each day, picks the top stories matching your interests, summarises each one with a local LLM, and delivers them to you via Telegram.

## What it does

1. Fetches the HN front page
2. Scores stories against configurable interest keywords (AI, cybersecurity, ethics, philosophy by default)
3. Picks the top 5 matches
4. Downloads and cleans each article
5. Summarises each article using a local LLM via [lemonade-server](https://github.com/lemonade-sdk/lemonade) (OpenAI-compatible API)
6. Sends one Telegram message per story with summary + key takeaways + links

## Requirements

- Python 3.10+
- A running [lemonade-server](https://github.com/lemonade-sdk/lemonade) instance (local LLM — tested with `Gemma-3-4b-it-GGUF`)
- A [Telegram bot token](https://core.telegram.org/bots#how-do-i-create-a-bot)
- Your Telegram numeric chat ID

## Installation

```bash
git clone https://github.com/rarmknecht/hndaily.git
cd hndaily
pip install -r requirements.txt
```

## Configuration

Set the following environment variables (or put them in a `.env` file in the project directory):

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | ✅ | — | Telegram bot token from @BotFather |
| `OWNER_ID` | ✅ | — | Your Telegram numeric chat ID |
| `LEMONADE_URL` | ❌ | `http://localhost:8000/v1` | Base URL for your lemonade-server instance |
| `LEMONADE_MODEL` | ❌ | `Gemma-3-4b-it-GGUF` | Model name to use for summarisation |

Example `.env`:

```env
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
OWNER_ID=987654321
LEMONADE_URL=http://localhost:8000/v1
LEMONADE_MODEL=Gemma-3-4b-it-GGUF
```

## Usage

```bash
python hn_daily.py
```

### Run on a schedule (cron)

To receive your daily digest automatically, add a cron job:

```bash
# Run every morning at 7 AM
0 7 * * * cd /path/to/hndaily && python hn_daily.py >> hn_daily.log 2>&1
```

## Customising interests

Edit the `INTEREST_KEYWORDS` dict in `hn_daily.py` to tune which stories get picked. Each keyword maps to a score weight — higher weight = stronger preference.

## License

MIT — see [LICENSE](LICENSE)
