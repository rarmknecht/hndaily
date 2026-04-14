#!/usr/bin/env python3
"""
HN Daily — Hacker News front page digest via Telegram
Pulls top 5 stories matching AI / cybersecurity / ethics / philosophy,
summarises each with a local LLM (Gemma via lemonade-server), and sends
a Telegram message per article.
"""

import json
import os
import re
import sys
import time
import textwrap
import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Retry helper — wraps requests.post with exponential backoff
# ---------------------------------------------------------------------------
def post_with_retry(url, retries: int = 3, backoff: float = 5.0, **kwargs):
    """POST with up to `retries` attempts, doubling backoff on each failure (backoff in minutes)."""
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, **kwargs)  # nosec B113 — timeout in **kwargs  # pylint: disable=missing-timeout
            return r
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ReadTimeout) as e:
            last_exc = e
            if attempt < retries:
                wait = backoff * (2 ** (attempt - 1))
                print(f"   ⚠️  Attempt {attempt}/{retries} failed ({e}). Retrying in {wait:.0f}m…")
                time.sleep(wait * 60)
    raise last_exc


# ---------------------------------------------------------------------------
# Config — reads from environment (or .env if python-dotenv is installed)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    # Walk up from this script to find a .env
    for _d in [
        os.path.dirname(__file__),
        os.path.expanduser("~"),
    ]:
        _f = os.path.join(_d, ".env")
        if os.path.exists(_f):
            load_dotenv(_f)
            break
except ImportError:
    pass

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("OWNER_ID", "")   # OWNER_ID is the numeric chat id
LEMONADE_URL = os.environ.get("LEMONADE_URL", "http://localhost:8000/v1")
LEMONADE_MODEL = os.environ.get("LEMONADE_MODEL", "Gemma-3-4b-it-GGUF")

if not BOT_TOKEN or not CHAT_ID:
    sys.exit(
        "Missing credentials. Set BOT_TOKEN and OWNER_ID "
        "in your environment or a .env file."
    )

# ---------------------------------------------------------------------------
# Interest keywords — scored per story title
# ---------------------------------------------------------------------------
INTEREST_KEYWORDS = {
    # AI / ML
    "ai": 3, "llm": 3, "gpt": 3, "claude": 3, "gemini": 3, "machine learning": 3,
    "neural": 2, "deep learning": 3, "generative": 2, "openai": 3, "anthropic": 3,
    "transformer": 2, "model": 1, "inference": 1, "embedding": 2, "agent": 2,
    "automation": 1, "robotics": 1,
    # Cybersecurity
    "security": 3, "cyber": 3, "hack": 2, "exploit": 3, "vulnerability": 3,
    "malware": 3, "ransomware": 3, "breach": 3, "cve": 3, "zero-day": 3,
    "phishing": 2, "cryptography": 2, "encryption": 2, "privacy": 2,
    "surveillance": 2, "nsa": 2, "fbi": 1,
    # Ethics
    "ethics": 3, "bias": 2, "fairness": 2, "accountability": 2, "regulation": 2,
    "copyright": 2, "rights": 1, "policy": 1, "governance": 2, "trust": 1,
    "misinformation": 2, "disinformation": 2, "censorship": 2,
    # Philosophy / society
    "philosophy": 3, "consciousness": 3, "existential": 2, "meaning": 1,
    "society": 1, "democracy": 2, "freedom": 1, "truth": 1, "knowledge": 1,
    "epistemology": 3, "metaphysics": 3, "cognition": 2,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# Step 1 — Scrape HN front page
# ---------------------------------------------------------------------------
def fetch_hn_stories() -> list[dict]:
    """Return list of dicts with title, url, hn_id."""
    resp = requests.get("https://news.ycombinator.com", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    stories = []
    for row in soup.select("tr.athing"):
        hn_id = row.get("id", "")
        title_span = row.select_one("span.titleline > a")
        if not title_span:
            continue
        title = title_span.get_text(strip=True)
        url = title_span.get("href", "")
        # Skip HN-internal "Ask HN" / "Show HN" items that have no real article
        if url.startswith("item?id="):
            url = f"https://news.ycombinator.com/{url}"
        stories.append({"title": title, "url": url, "hn_id": hn_id})

    return stories


# ---------------------------------------------------------------------------
# Step 2 — Score & pick top N
# ---------------------------------------------------------------------------
def score_story(title: str) -> int:
    """Return interest score for a story title based on keyword matches."""
    t = title.lower()
    return sum(v for k, v in INTEREST_KEYWORDS.items() if k in t)


def pick_top(stories: list[dict], n: int = 5) -> list[dict]:
    """Return the top-n stories sorted by interest score descending."""
    scored = sorted(stories, key=lambda s: score_story(s["title"]), reverse=True)
    return scored[:n]


# ---------------------------------------------------------------------------
# Step 3 — Fetch & clean article text
# ---------------------------------------------------------------------------
def fetch_article_text(url: str, max_chars: int = 8000) -> str:
    """Download URL, strip boilerplate, return plain text (truncated).

    Note: this function fetches arbitrary third-party URLs sourced from HN.
    That is intentional behaviour; callers should not pass untrusted local
    addresses (SSRF risk if the script is ever exposed as a service).
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:  # pylint: disable=broad-exception-caught  # network errors are diverse
        return f"[Could not fetch article: {e}]"

    soup = BeautifulSoup(resp.text, "html.parser")
    # Remove noise tags
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "form", "noscript", "iframe"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # Collapse blank lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines)
    return text[:max_chars]


# ---------------------------------------------------------------------------
# Step 4 — Summarise with local Gemma via lemonade-server
# ---------------------------------------------------------------------------
def summarise(title: str, article_text: str) -> dict:
    """Call local Gemma-3-4b-it via lemonade-server and return {summary, key_points}."""
    prompt = textwrap.dedent(f"""
        Read the article below and return ONLY a valid JSON object with exactly two keys:
          "summary"    — 3-4 sentence overview of the article
          "key_points" — list of 3-5 short bullet strings (each 20 words or fewer)

        Do not include any text before or after the JSON object.

        Article title: {title}

        Article text:
        {article_text}
    """).strip()

    payload = {
        "model": LEMONADE_MODEL,
        "max_tokens": 600,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = requests.post(
        f"{LEMONADE_URL}/chat/completions",
        headers={"content-type": "application/json"},
        json=payload,
        timeout=120,  # local inference can be slower than cloud
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()

    # Extract JSON block (model may wrap in ```json ... ```)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    # Fallback: return raw text as summary
    return {"summary": raw, "key_points": []}


# ---------------------------------------------------------------------------
# Step 5 — Send Telegram message
# ---------------------------------------------------------------------------
def escape_md2(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(r"([" + re.escape(special) + r"])", r"\\\1", text)


def send_telegram(story: dict, analysis: dict) -> None:
    """Format and dispatch a Telegram message for one story."""
    title = story["title"]
    url = story["url"]
    hn_url = f"https://news.ycombinator.com/item?id={story['hn_id']}"
    summary = analysis.get("summary", "No summary available.")
    key_points = analysis.get("key_points", [])

    bullets = "\n".join(f"• {p}" for p in key_points) if key_points else "• (none)"

    def md2(s: str) -> str:
        return escape_md2(str(s))

    text_md2 = (
        f"*{md2(title)}*\n\n"
        f"{md2(summary)}\n\n"
        f"*Key Takeaways:*\n"
        + "\n".join(f"• {md2(p)}" for p in key_points)
        + f"\n\n[HN Discussion]({hn_url})  |  [Article]({url})"
    )

    # NOTE: BOT_TOKEN is embedded in the Telegram API URL — this is required by the
    # Telegram Bot API design. Avoid logging this URL at ERROR level or above to
    # prevent accidental token exposure in log aggregators.
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = post_with_retry(api_url, retries=3, backoff=5.0, json={
        "chat_id": CHAT_ID,
        "text": text_md2,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": False,
    }, timeout=15)

    if r.ok:
        return

    # --- Fallback: plain text ---
    text_plain = (
        f"📰 {title}\n\n"
        f"{summary}\n\n"
        f"Key Takeaways:\n{bullets}\n\n"
        f"🔗 HN: {hn_url}\n"
        f"🔗 Article: {url}"
    )
    post_with_retry(api_url, retries=3, backoff=5.0, json={
        "chat_id": CHAT_ID,
        "text": text_plain,
        "disable_web_page_preview": False,
    }, timeout=15)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    """Fetch HN front page, pick top stories, summarise, and dispatch to Telegram."""
    print("📡 Fetching HN front page…")
    stories = fetch_hn_stories()
    print(f"   Found {len(stories)} stories")

    top = pick_top(stories, n=5)
    print("\n🏆 Top 5 picks:")
    for i, s in enumerate(top, 1):
        score = score_story(s["title"])
        print(f"   {i}. [{score}] {s['title']}")

    for i, story in enumerate(top, 1):
        print(f"\n🔍 [{i}/5] Processing: {story['title'][:60]}…")

        print("   Fetching article text…")
        article_text = fetch_article_text(story["url"])

        print("   Summarising with Gemma-3-4b (local)…")
        analysis = summarise(story["title"], article_text)

        print("   Sending Telegram message…")
        send_telegram(story, analysis)
        print("   ✅ Sent!")

        # Be polite between API calls
        if i < len(top):
            time.sleep(2)

    print("\n✅ All done!")


if __name__ == "__main__":
    main()
