"""
FeedBot — Keyword-filtered RSS/web scraper → Telegram channel poster
"""

import sqlite3
import hashlib
import time
import re
import unicodedata
import logging
import os
from pathlib import Path
from urllib.parse import urlparse, urljoin, quote

import feedparser
import requests
from bs4 import BeautifulSoup

from proxy_utils import normalize_proxy_environment

normalize_proxy_environment()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("feedbot")

DB_PATH = Path(__file__).parent / "data" / "feedbot.db"
CONFIG_PATH = Path(__file__).parent / "data" / "config.json"


# ──────────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────────

def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL,
            url     TEXT NOT NULL UNIQUE,
            type    TEXT NOT NULL DEFAULT 'rss',   -- 'rss' or 'web'
            active  INTEGER NOT NULL DEFAULT 1,
            added   TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS keywords (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            word    TEXT NOT NULL UNIQUE,
            active  INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS sent_articles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            hash        TEXT NOT NULL UNIQUE,
            title       TEXT,
            url         TEXT,
            source      TEXT,
            sent_at     TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key     TEXT PRIMARY KEY,
            value   TEXT
        );
    """)
    con.commit()
    con.close()


def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def get_setting(key, default=None):
    with get_db() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with get_db() as con:
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))


# ──────────────────────────────────────────────
# CONFIG HELPERS
# ──────────────────────────────────────────────

def get_sources():
    with get_db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM sources WHERE active=1").fetchall()]


def get_keywords():
    with get_db() as con:
        rows = con.execute("SELECT word FROM keywords WHERE active=1").fetchall()
        return [r["word"].lower() for r in rows]


def article_seen(url):
    h = hashlib.md5(url.encode()).hexdigest()
    with get_db() as con:
        return con.execute("SELECT 1 FROM sent_articles WHERE hash=?", (h,)).fetchone() is not None


def mark_sent(title, url, source):
    h = hashlib.md5(url.encode()).hexdigest()
    with get_db() as con:
        try:
            con.execute(
                "INSERT INTO sent_articles(hash,title,url,source) VALUES(?,?,?,?)",
                (h, title, url, source)
            )
        except sqlite3.IntegrityError:
            pass


# ──────────────────────────────────────────────
# KEYWORD MATCHING
# ──────────────────────────────────────────────

def matches_keywords(text, keywords):
    if not keywords:
        return False
    text_norm = unicodedata.normalize('NFKC', text.lower())
    return any(unicodedata.normalize('NFKC', kw) in text_norm for kw in keywords)


def _get_proxy_config():
    """Return an empty explicit proxy config and rely on normalized env vars."""
    return {}


def _build_session():
    """Build a requests session with normalized environment proxy support."""
    session = requests.Session()
    session.trust_env = True
    session.proxies.update(_get_proxy_config())
    return session


def request_without_proxy(method, url, **kwargs):
    with _build_session() as session:
        return session.request(method, url, **kwargs)


# ──────────────────────────────────────────────
# RSS SCRAPER
# ──────────────────────────────────────────────

def scrape_rss(source, keywords):
    articles = []
    try:
        resp = request_without_proxy("GET", source["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        log.info(f"[RSS] {source['name']} → {len(feed.entries)} entries")
        for entry in feed.entries:
            title   = entry.get("title", "")
            link    = entry.get("link", "")
            summary = entry.get("summary", "")
            content = entry.get("content", [{}])
            body    = content[0].get("value", "") if content else ""
            full    = f"{title} {summary} {body}"

            if not link or article_seen(link):
                continue

            if matches_keywords(full, keywords):
                articles.append({
                    "title":   title,
                    "url":     link,
                    "summary": BeautifulSoup(summary, "html.parser").get_text()[:400],
                    "content": BeautifulSoup(body or summary, "html.parser").get_text("\n\n", strip=True),
                    "source":  source["name"],
                })
    except Exception as e:
        log.error(f"[RSS] Error scraping {source['name']}: {e}")
    return articles


# ──────────────────────────────────────────────
# WEB SCRAPER (full blog / article list)
# ──────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

SKIP_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg",
                   ".mp4", ".mp3", ".zip", ".gz", ".tar", ".exe", ".dmg"}

def _normalise_url(url, base):
    url = urljoin(base, url)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    clean = f"{parsed.scheme}://{parsed.netloc}{path}{query}"
    clean = clean.split("#")[0]
    ext = Path(parsed.path).suffix.lower()
    if ext in SKIP_EXTENSIONS:
        return None
    return clean


def _get_original_path(url):
    """Get the original URL path before normalization, preserving trailing slashes for detection."""
    parsed = urlparse(url)
    return parsed.path


def _same_domain(url, base_domain):
    return urlparse(url).netloc.replace("www.", "") == base_domain.replace("www.", "")


def _is_article_url(path):
    """Check if URL looks like a single article/page, not a listing or index page.
    
    Args:
        path: URL path, may or may not have trailing slash.
        Stripped trailing slashes are already removed by _normalise_url.
    """
    path_lower = path.lower().rstrip('/')
    
    # Empty path or root - not an article
    if path_lower in ('', '/'):
        return False
    
    # Match common article URL patterns
    patterns = [
        r"/\d{4}/\d{2}/",          # /2024/01/
        r"/\d{4}/\d{2}/\d{2}/",    # /2024/01/15/
        r"/post/",                  # /post/
        r"/article/",               # /article/
        r"/blog/",                  # /blog/
        r"/p/",                     # /p/
        r"/news/.",                 # /news/something (any char after /news/)
    ]
    for pattern in patterns:
        if re.search(pattern, path_lower):
            return True
    
    # If path has more than 2 segments (e.g., /news/something), likely an article
    segments = [s for s in path_lower.split('/') if s]
    if len(segments) >= 2:
        # /news/article-name or /2024/01/15/article
        return True
    
    # Single segment like /about or /contact - not an article listing
    return False


def _crawl_page(url, keywords, source_name, visited, queued, queue, base_domain, articles):
    """Fetch a page, check for keywords, optionally extract links."""
    normalised = _normalise_url(url, url)
    if not normalised or normalised in visited:
        return
    if not _same_domain(normalised, base_domain):
        return
    visited.add(normalised)

    try:
        resp = request_without_proxy("GET", normalised, headers=HEADERS, timeout=10)
        if "text/html" not in resp.headers.get("Content-Type", ""):
            return

        soup = BeautifulSoup(resp.text, "html.parser")

        # 1. Extract links BEFORE decomposing (article links can be in <header>/<nav>)
        is_article = _is_article_url(urlparse(normalised).path)
        found = 0
        if not is_article:
            for a in soup.find_all("a", href=True):
                link = _normalise_url(a["href"], normalised)
                if (link and link not in visited and link not in queued
                        and _same_domain(link, base_domain)):
                    queued.add(link)
                    if _is_article_url(urlparse(link).path):
                        queue.insert(0, link)
                    else:
                        queue.append(link)
                    found += 1

        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else normalised
        body_text = extract_text_from_soup(soup)

        full = f"{title} {body_text}"
        if not article_seen(normalised) and matches_keywords(full, keywords):
            articles.append({
                "title":   title[:120],
                "url":     normalised,
                "summary": body_text[:400],
                "content": body_text,
                "source":  source_name,
            })

        log.info(f"[WEB] {'ARTICLE ' if is_article else ''}Crawled {normalised}"
                 f" — {found} new links queued"
                 f"  (visited {len(visited)}, queue {len(queue)}, matches {len(articles)})")
        time.sleep(0.3)
    except Exception:
        pass


def scrape_web(source, keywords):
    articles = []
    url = source["url"]

    # Search mode: URL contains {keyword} placeholder
    if "{keyword}" in url:
        for kw in keywords:
            search_url = url.replace("{keyword}", quote(kw))
            log.info(f"[WEB] Search URL: {search_url}")

            try:
                resp = request_without_proxy("GET", search_url, headers=HEADERS, timeout=15)
                ct = resp.headers.get("Content-Type", "")

                if "application/json" in ct or search_url.endswith(".json"):
                    # JSON API response — extract articles directly
                    data = resp.json()
                    items = (data.get("results") or data.get("hits")
                             or data.get("data") or data.get("items") or [])
                    for item in items:
                        if isinstance(item, dict):
                            source_data = item.get("_source", item)
                            title = (source_data.get("post_title")
                                     or source_data.get("title")
                                     or source_data.get("name") or "")
                            link = (source_data.get("permalink")
                                    or source_data.get("link")
                                    or source_data.get("url") or "")
                            excerpt = (source_data.get("post_excerpt")
                                       or source_data.get("excerpt")
                                       or source_data.get("description") or "")
                            if link and not article_seen(link):
                                articles.append({
                                    "title":   str(title)[:120],
                                    "url":     link,
                                    "summary": BeautifulSoup(str(excerpt), "html.parser").get_text()[:400],
                                    "content": BeautifulSoup(str(excerpt), "html.parser").get_text("\n\n", strip=True),
                                    "source":  source["name"],
                                })
                    log.info(f"[WEB] {source['name']} search '{kw}' — "
                             f"API returned {len(articles)} articles")
                else:
                    # HTML search page — crawl as usual
                    visited = set()
                    queued = set()
                    queue = [search_url]
                    queued.add(search_url)
                    base_domain = urlparse(url).netloc
                    max_pages = 100

                    while queue and len(visited) < max_pages:
                        page_url = queue.pop(0)
                        _crawl_page(page_url, keywords, source["name"],
                                    visited, queued, queue, base_domain, articles)

                    log.info(f"[WEB] {source['name']} search '{kw}' "
                             f"— crawled {len(visited)} pages, {len(articles)} matches")
            except Exception as e:
                log.error(f"[WEB] Search failed for '{kw}': {e}")

        return articles

    # Normal crawl mode: BFS from source URL
    visited = set()
    queued = set()
    queue = [url]
    queued.add(url)
    base_domain = urlparse(url).netloc
    
    # Check if the source URL itself looks like a single article
    is_article = _is_article_url(urlparse(url).path)
    
    # If it's a single article, only scan that one page (no link crawling)
    # Otherwise, crawl but with a reasonable default limit
    if is_article:
        max_pages = 1  # Only scan the single URL provided
        log.info(f"[WEB] {source['name']} — detected as article URL, scanning only this page")
    else:
        max_pages = 50  # Default crawl limit for listing/index pages
    
    page_count = 0
    while queue and len(visited) < max_pages and page_count < max_pages:
        page_url = queue.pop(0)
        _crawl_page(page_url, keywords, source["name"],
                    visited, queued, queue, base_domain, articles)
        page_count += 1

    log.info(f"[WEB] {source['name']} — crawl done: {len(visited)} pages, {len(articles)} matches")
    return articles


# ──────────────────────────────────────────────
# TELEGRAM SENDER
# ──────────────────────────────────────────────

TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_SAFE_LIMIT = 3900


def extract_text_from_soup(soup):
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()

    body_tag = (
        soup.find("article") or
        soup.find("main") or
        soup.find(class_=re.compile(r"post|entry|content|article", re.I))
    )
    search_area = body_tag if body_tag else soup

    content_parts = []
    for tag in search_area.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6"]):
        text = tag.get_text(" ", strip=True)
        if text:
            content_parts.append(text)

    return "\n\n".join(content_parts)


def fetch_full_article(article):
    url = article.get("url", "")
    fallback = article.get("content") or article.get("summary") or ""

    if not url:
        return fallback

    try:
        resp = request_without_proxy("GET", url, headers=HEADERS, timeout=15)
        if "text/html" not in resp.headers.get("Content-Type", ""):
            return fallback

        soup = BeautifulSoup(resp.text, "html.parser")
        body = extract_text_from_soup(soup)
        return body or fallback
    except Exception as e:
        log.warning(f"[ARTICLE] Could not fetch full article, using scraped text: {e}")
        return fallback


def split_telegram_message(text, max_chars=TELEGRAM_SAFE_LIMIT):
    text = str(text or "").strip()
    if not text:
        return []

    parts = []
    current = ""

    for paragraph in re.split(r"\n{2,}", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(paragraph) > max_chars:
            if current:
                parts.append(current.strip())
                current = ""
            for start in range(0, len(paragraph), max_chars):
                parts.append(paragraph[start:start + max_chars].strip())
            continue

        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
        else:
            parts.append(current.strip())
            current = paragraph

    if current:
        parts.append(current.strip())

    return parts


def fit_single_telegram_message(text, max_chars=TELEGRAM_SAFE_LIMIT):
    text = str(text or "").strip()
    if len(text) <= max_chars:
        return text

    source_match = re.search(r"\n\nمنبع اصلی:\n\S+\s*$", text)
    source_block = source_match.group(0).strip() if source_match else ""
    suffix = f"\n\n{source_block}" if source_block else ""
    ellipsis = "\n\n..."
    body_limit = max_chars - len(suffix) - len(ellipsis)

    if body_limit <= 0:
        return text[:max_chars].strip()

    body = text[:body_limit].rsplit("\n", 1)[0].strip()
    if not body:
        body = text[:body_limit].strip()

    return f"{body}{ellipsis}{suffix}".strip()


def build_translated_article_message(article):
    from translator import translate_article

    title = article.get("title", "")
    source_url = article.get("url", "")
    body = fetch_full_article(article)

    if not body.strip():
        body = article.get("summary", "")

    return translate_article(title, body, source_url)


def post_telegram_messages(bot_token, channel, messages, title):
    session = _build_session()
    for index, message in enumerate(messages, start=1):
        suffix = f" ({index}/{len(messages)})" if len(messages) > 1 else ""
        r = session.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": channel,
                "text": message[:TELEGRAM_MESSAGE_LIMIT],
                "disable_web_page_preview": index == len(messages),
            },
            timeout=15,
        )
        data = r.json()
        if not data.get("ok"):
            log.error(f"[TG] Error{suffix}: {data.get('description')}")
            return False

        log.info(f"[TG] ✓ Sent{suffix}: {title[:60]}")
        time.sleep(1)

    return True


def send_to_telegram(article):
    bot_token = get_setting("telegram_bot_token")
    channel   = get_setting("telegram_channel")

    if not bot_token or not channel:
        log.warning("Telegram not configured — skipping send.")
        return False

    try:
        text = build_translated_article_message(article)
        message = fit_single_telegram_message(text)
        if not message:
            log.warning("[TG] Nothing to send after translation.")
            return False

        return post_telegram_messages(
            bot_token,
            channel,
            [message],
            article.get("title", "No title"),
        )
    except Exception as e:
        log.error(f"[TG] Request failed: {e}")
    return False


def escape_md(text):
    """Escape MarkdownV2 special characters."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special)}])", r"\\\1", str(text))


# ──────────────────────────────────────────────
# MAIN RUN CYCLE
# ──────────────────────────────────────────────

def run_cycle(dry_run=False):
    sources  = get_sources()
    keywords = get_keywords()

    if not sources:
        log.warning("No active sources configured.")
        return
    if not keywords:
        log.warning("No keywords configured.")
        return

    label = "DRY RUN" if dry_run else "LIVE"
    log.info(f"▶ [{label}] Running cycle — {len(sources)} sources, keywords: {keywords}")
    total = 0

    for source in sources:
        if source["type"] == "rss":
            articles = scrape_rss(source, keywords)
        else:
            articles = scrape_web(source, keywords)

        for article in articles:
            if dry_run:
                mark_sent(article["title"], article["url"], article["source"])
                log.info(f"[{label}] 📄 Marked seen: {article['title'][:60]}")
                total += 1
            else:
                ok = send_to_telegram(article)
                if ok:
                    mark_sent(article["title"], article["url"], article["source"])
                    total += 1
                    time.sleep(2)

    log.info(f"✅ [{label}] Cycle done — {total} articles {'indexed' if dry_run else 'sent'}.")
    return total


if __name__ == "__main__":
    init_db()
    run_cycle()
