"""
WebSearch Module — Search the web, collect links, scrape content, send to Telegram.
Uses Startpage (private Google results) as primary search backend.
"""

import logging
import time
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote_plus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("web_search")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def search_startpage(keywords, max_results=10):
    """
    Search using Startpage (private Google results).
    Returns a list of dicts with 'title', 'url', 'snippet'.
    """
    results = []
    seen_urls = set()

    for keyword in keywords:
        try:
            url = (
                f"https://startpage.com/do/search"
                f"?q={quote_plus(keyword)}"
                f"&catalog=web"
                f"&size=5"
                f"&language=English"
                f"&format=basic"
            )
            
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")

            # Find all anchor tags with external URLs
            all_a = soup.find_all("a", href=True)
            
            for a in all_a:
                href = a["href"]
                text = a.get_text(strip=True)
                
                # Skip if no meaningful text
                if not text or len(text) < 3:
                    continue
                    
                # Skip Startpage internal links
                if "startpage.com" in href:
                    continue
                    
                # Only process HTTP(S) links
                if not href.startswith("http"):
                    continue
                
                # Skip if we've seen this URL
                if href in seen_urls:
                    continue
                    
                seen_urls.add(href)
                
                results.append({
                    "title": text[:120],
                    "url": href,
                    "snippet": "",
                    "keyword": keyword,
                })
                
                if len(results) >= max_results:
                    break
                    
        except Exception as e:
            log.error(f"[SEARCH] Startpage search failed for '{keyword}': {e}")
            time.sleep(1)

    log.info(f"[SEARCH] Found {len(results)} unique results from Startpage")
    return results[:max_results]


def search_ddg(keywords, max_results=10):
    """
    Search using DuckDuckGo HTML endpoint as fallback.
    """
    results = []
    seen_urls = set()

    for keyword in keywords:
        try:
            url = f"https://html.duckduckduck.com/?q={quote_plus(keyword)}&cb=_getResults"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.encoding = "utf-8"
            
            # Extract JSON from _getResults(...) callback
            match = re.search(r"_getResults\s*\((.*?)\)", resp.text)
            if match:
                data = json.loads(match.group(1))
                for item in data.get("Results", [])[:5]:
                    url = item.get("Url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        results.append({
                            "title": item.get("Title", "")[:120],
                            "url": url,
                            "snippet": item.get("Snippet", "")[:300],
                            "keyword": keyword,
                        })
        except Exception as e:
            log.debug(f"[SEARCH] DuckDuckGo API failed for '{keyword}': {e}")

    log.info(f"[SEARCH] Found {len(results)} unique results from DuckDuckGo")
    return results[:max_results]


def search_web(keywords, max_results=10):
    """
    Try multiple search backends in order of reliability.
    Returns a list of dicts with 'title', 'url', 'snippet'.
    """
    results = []
    seen_urls = set()

    # First try: Startpage (most reliable free option)
    log.info("[SEARCH] Trying Startpage...")
    sp_results = search_startpage(keywords, max_results=max_results)
    for r in sp_results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            results.append(r)

    # If Startpage failed, try DuckDuckGo
    if not results:
        log.info("[SEARCH] Trying DuckDuckGo...")
        ddg_results = search_ddg(keywords, max_results=max_results)
        for r in ddg_results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                results.append(r)

    log.info(f"[SEARCH] Total: {len(results)} unique results")
    return results[:max_results]


def scrape_page(url, timeout=10):
    """
    Open and scrape a single URL.
    Returns dict with 'title', 'content', 'url'.
    Only extracts text from <p> and <h> tags to exclude related posts, navigation, etc.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
        if "text/html" not in resp.headers.get("Content-Type", ""):
            return {"title": "", "content": "", "url": url}

        soup = BeautifulSoup(resp.text, "html.parser")

        title = soup.find("title")
        title_text = title.get_text(strip=True) if title else urlparse(url).netloc

        from feedbot import extract_text_from_soup
        content = extract_text_from_soup(soup)

        return {
            "title": title_text[:200],
            "content": content,
            "url": url,
        }
    except Exception as e:
        log.error(f"[SCRAPE] Error scraping {url}: {e}")
        return {"title": "", "content": "", "url": url}


def scrape_all_links(urls, timeout=10):
    """
    Open and scrape multiple URLs.
    Returns list of dicts with 'title', 'content', 'url'.
    """
    articles = []
    for i, url in enumerate(urls):
        log.info(f"[SCRAPE] Opening link {i+1}/{len(urls)}: {url[:80]}")
        article = scrape_page(url, timeout=timeout)
        articles.append(article)
        time.sleep(0.5)  # Be polite to servers
    return articles


def send_links_to_telegram(links, bot_token=None, channel=None):
    """
    Send collected links to Telegram channel.
    Each link is sent as a formatted message with title and URL.
    Returns count of successfully sent messages.
    """
    from feedbot import get_setting, mark_sent, send_to_telegram

    if not bot_token:
        bot_token = get_setting("telegram_bot_token")
    if not channel:
        channel = get_setting("telegram_channel")

    if not bot_token or not channel:
        log.warning("Telegram not configured — skipping send.")
        return 0

    sent_count = 0
    for link in links:
        try:
            title = link.get("title", "No title")
            url = link.get("url", "")
            article = {
                "title": title,
                "url": url,
                "summary": link.get("content", ""),
                "content": link.get("content", ""),
                "source": link.get("source", "web_search"),
            }

            if send_to_telegram(article):
                log.info(f"[TG] ✓ Sent: {title[:60]}")
                mark_sent(title, url, "web_search")
                sent_count += 1
                time.sleep(2)
        except Exception as e:
            log.error(f"[TG] Failed to send: {e}")

    return sent_count


def search_sources(keywords, max_results=10, scrape_content=True, send_telegram=True):
    """
    Search through configured source sites (RSS feeds and websites) instead of internet.
    Uses the same source scraping logic as feedbot.py but returns results for display.
    
    Args:
        keywords: list of search keywords
        max_results: max number of results to return
        scrape_content: whether to scrape full content from sources
        send_telegram: whether to send results to Telegram
    
    Returns:
        dict with 'links' (list) and 'sent_count' (int)
    """
    from feedbot import get_sources, scrape_rss, scrape_web, send_to_telegram, mark_sent, extract_text_from_soup
    import time as time_mod
    
    log.info("[SOURCE-SEARCH] Starting source-based search with keywords: %s", keywords)
    
    # Step 1: Get active sources
    sources = get_sources()
    if not sources:
        log.warning("[SOURCE-SEARCH] No active sources configured")
        return {"links": [], "sent_count": 0}
    
    log.info("[SOURCE-SEARCH] Found %d active sources", len(sources))
    
    # Step 2: Scrape each source
    all_articles = []
    for source in sources:
        try:
            if source.get("type") == "rss":
                articles = scrape_rss(source, keywords)
            else:
                articles = scrape_web(source, keywords)
            
            log.info("[SOURCE-SEARCH] %s → %d matches", source["name"], len(articles))
            all_articles.extend(articles)
            
            if len(all_articles) >= max_results:
                break
        except Exception as e:
            log.error("[SOURCE-SEARCH] Error scraping source '%s': %s", source["name"], e)
    
    log.info("[SOURCE-SEARCH] Total matches from sources: %d", len(all_articles))
    
    # Step 3: Limit results
    articles = all_articles[:max_results]
    
    # Step 4: Scrape additional content if requested
    if scrape_content and articles:
        log.info("[SOURCE-SEARCH] Scraping additional content from %d articles", len(articles))
        for article in articles:
            try:
                resp = requests.get(article["url"], headers=HEADERS, timeout=10, verify=False)
                if "text/html" in resp.headers.get("Content-Type", ""):
                    soup = BeautifulSoup(resp.text, "html.parser")
                    article["content"] = extract_text_from_soup(soup)
            except Exception as e:
                log.error("[SOURCE-SEARCH] Error scraping content for %s: %s", article.get("url"), e)
    
    # Step 5: Send to Telegram if requested
    sent_count = 0
    if send_telegram:
        for article in articles:
            try:
                if send_to_telegram(article):
                    log.info("[SOURCE-SEARCH] ✓ Sent to Telegram: %s", article.get("title", "")[:60])
                    mark_sent(article.get("title", ""), article["url"], "source_search")
                    sent_count += 1
                    time_mod.sleep(2)
            except Exception as e:
                log.error("[SOURCE-SEARCH] Failed to send article to Telegram: %s", e)
    
    log.info("[SOURCE-SEARCH] Done. Sent %d articles to Telegram.", sent_count)
    return {"links": articles, "sent_count": sent_count}


def search_scrape_and_send(keywords, max_links=10, scrape_content=True, send_telegram=True):
    """
    Main function: search → collect links → open/scrape → send.
    
    Args:
        keywords: list of search keywords
        max_links: max number of search results to collect
        scrape_content: whether to open each link and scrape content
        send_telegram: whether to send results to Telegram
    
    Returns:
        dict with 'links' (list) and 'sent_count' (int)
    """
    log.info(f"[SEARCH-SEND] Starting with keywords: {keywords}")

    # Step 1: Search
    search_results = search_web(keywords, max_results=max_links)
    if not search_results:
        log.warning("[SEARCH-SEND] No search results found")
        return {"links": [], "sent_count": 0}

    # Step 2: Collect URLs
    urls = [r["url"] for r in search_results if r.get("url")]
    log.info(f"[SEARCH-SEND] Collected {len(urls)} URLs")

    if scrape_content:
        # Step 3: Open and scrape each link
        log.info("[SEARCH-SEND] Opening and scraping links...")
        scraped = scrape_all_links(urls)
    else:
        # Just return search results without scraping
        scraped = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("snippet", ""),
            }
            for r in search_results
        ]

    # Step 4: Send to Telegram
    sent_count = 0
    if send_telegram:
        sent_count = send_links_to_telegram(scraped)

    log.info(f"[SEARCH-SEND] Done. Sent {sent_count} links to Telegram.")
    return {"links": scraped, "sent_count": sent_count}
