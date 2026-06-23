# 🤖 FeedBot — Keyword-Filtered Feed Aggregator → Telegram

Monitor RSS feeds and websites for articles matching your keywords, and automatically post them to a Telegram channel.

---

## Features

- **RSS + Web scraping**: supports any RSS/Atom feed AND regular blog/news websites
- **Keyword filtering**: only articles matching your keywords get posted
- **Deduplication**: never sends the same article twice (SQLite tracking)
- **Telegram integration**: posts rich messages with title, summary, and link
- **Web dashboard**: manage sources, keywords, and settings in your browser
- **Scheduler**: auto-runs every N minutes in the background

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Create your Telegram Bot
1. Open Telegram → search for **@BotFather**
2. Send `/newbot`, follow the prompts, copy your **bot token**
3. Add the bot as **admin** to your channel (it needs permission to post)
4. Get your channel ID:
   - Public channels: use `@yourchannel` (with the @)
   - Private channels: use the numeric ID like `-100123456789`
   - To find the numeric ID: forward a message from the channel to [@userinfobot](https://t.me/userinfobot)

### 3. Run the dashboard
```bash
python dashboard.py
```
Open [http://localhost:5000](http://localhost:5000) in your browser.

In the dashboard:
1. Enter your **Bot Token** and **Channel ID** under Telegram Settings → Save
2. Add **keywords** (e.g. `artificial intelligence`, `python`, `climate change`)
3. Add **sources** — either RSS feed URLs or regular website URLs

### 4. Run the scraper

**One-shot run** (from dashboard):
Click the **▶ Run Now** button in the dashboard.

**Scheduled run** (background):
```bash
python scheduler.py             # runs every 30 minutes
python scheduler.py --interval 60  # runs every 60 minutes
```

**Single manual run** (CLI):
```bash
python feedbot.py
```

---

## Source Types

| Type | When to use | Example URL |
|------|-------------|-------------|
| **RSS** | Site has an RSS/Atom feed | `https://techcrunch.com/feed/` |
| **Web** | No RSS, scrape the blog directly | `https://example.com/blog` |

### Common RSS feed URL patterns
- WordPress: `https://example.com/feed/`
- Medium: `https://medium.com/feed/@username`
- Substack: `https://name.substack.com/feed`
- YouTube channel: `https://www.youtube.com/feeds/videos.xml?channel_id=XXXXX`
- Reddit: `https://www.reddit.com/r/python/.rss`
- Hacker News: `https://hnrss.org/frontpage`

---

## Project Structure

```
feedbot/
├── feedbot.py       — core scraper + Telegram sender
├── dashboard.py     — Flask web UI
├── scheduler.py     — APScheduler background runner
├── requirements.txt
├── data/
│   └── feedbot.db   — SQLite database (auto-created)
└── README.md
```

---

## Tips

- **Be kind to servers**: the web scraper has built-in delays (0.5s between pages)
- **Prefer RSS when available**: it's faster, more reliable, and puts less load on the site
- **Multi-word keywords**: each keyword can be a phrase, e.g. `machine learning`
- **Channel must be public OR bot must be admin**: double-check this if posts aren't appearing

---

## Telegram Message Format

Each matched article is posted as:

```
📰 Article Title

Article summary text here (up to 350 characters)...

🔗 Read more
📡 Source: TechCrunch
```
