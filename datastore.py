"""SQLite datastore for HN Daily.

Records every story sent to Telegram so that:
  1. stories are never sent twice (dedupe by Hacker News item id), and
  2. the sent content can be queried independently by other apps.

The store is a single SQLite file (default ``hndaily.db`` next to the
script, overridable via the ``HNDAILY_DB`` environment variable). Any app
in any language can read it directly, e.g.:

    sqlite3 hndaily.db "SELECT title, summary, sent_at \
        FROM stories ORDER BY sent_at DESC LIMIT 10;"

Table ``stories``:
    hn_id         TEXT  PRIMARY KEY — Hacker News item id (stable, unique)
    title         TEXT
    article_url   TEXT             — link to the original article
    hn_url        TEXT             — link to the HN discussion
    score         INTEGER          — interest score at send time
    summary       TEXT             — LLM-generated summary
    key_points    TEXT             — JSON array of bullet strings
    article_text  TEXT             — cleaned article body as scraped
    sent_at       TEXT             — ISO 8601 UTC timestamp of delivery
"""

import json
import sqlite3
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    hn_id        TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    article_url  TEXT NOT NULL,
    hn_url       TEXT NOT NULL,
    score        INTEGER NOT NULL,
    summary      TEXT,
    key_points   TEXT,
    article_text TEXT,
    sent_at      TEXT NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open the datastore (creating the file and schema if needed)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def already_sent(conn: sqlite3.Connection, hn_id: str) -> bool:
    """Return True if a story with this HN item id has already been recorded."""
    row = conn.execute(
        "SELECT 1 FROM stories WHERE hn_id = ?", (hn_id,)
    ).fetchone()
    return row is not None


def record_story(conn: sqlite3.Connection, story: dict, score: int,
                 analysis: dict, article_text: str) -> None:
    """Persist a sent story. INSERT OR IGNORE — a no-op if hn_id already exists."""
    conn.execute(
        """INSERT OR IGNORE INTO stories
               (hn_id, title, article_url, hn_url, score,
                summary, key_points, article_text, sent_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            story["hn_id"],
            story["title"],
            story["url"],
            f"https://news.ycombinator.com/item?id={story['hn_id']}",
            score,
            analysis.get("summary", ""),
            json.dumps(analysis.get("key_points", [])),
            article_text,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
