"""
FeedBot Dashboard — lightweight Flask web UI
Run: python dashboard.py
"""

from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory
import sqlite3
import sys
import os
import time
sys.path.insert(0, os.path.dirname(__file__))

from feedbot import init_db, get_db, get_setting, set_setting, run_cycle
from web_search import search_scrape_and_send, search_sources

app = Flask(__name__)

# Serve static files (script.js)
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)


@app.route("/")
def index():
    init_db()
    with get_db() as con:
        sources  = [dict(r) for r in con.execute("SELECT * FROM sources ORDER BY id DESC").fetchall()]
        keywords = [dict(r) for r in con.execute("SELECT * FROM keywords ORDER BY word").fetchall()]
        sent     = [dict(r) for r in con.execute(
            "SELECT * FROM sent_articles ORDER BY sent_at DESC LIMIT 20"
        ).fetchall()]
    resp = app.make_response(render_template("index.html",
        sources=sources, keywords=keywords, sent=sent,
        bot_token=get_setting("telegram_bot_token"),
        channel=get_setting("telegram_channel"),
        msg=request.args.get("msg"),
        msg_type=request.args.get("mt", "ok"),
        timestamp=int(time.time()),
    ))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/sources/add", methods=["POST"])
def add_source():
    name = request.form["name"].strip()
    url  = request.form["url"].strip()
    typ  = request.form["type"]
    try:
        with get_db() as con:
            con.execute("INSERT INTO sources(name,url,type) VALUES(?,?,?)", (name, url, typ))
        return redirect(url_for("index", msg=f"Source '{name}' added!", mt="ok"))
    except Exception as e:
        return redirect(url_for("index", msg=str(e), mt="err"))


@app.route("/sources/delete/<int:sid>", methods=["POST"])
def delete_source(sid):
    with get_db() as con:
        con.execute("DELETE FROM sources WHERE id=?", (sid,))
    return redirect(url_for("index"))


@app.route("/sources/toggle/<int:sid>", methods=["POST"])
def toggle_source(sid):
    with get_db() as con:
        con.execute("UPDATE sources SET active = 1-active WHERE id=?", (sid,))
    return redirect(url_for("index"))


@app.route("/keywords/add", methods=["POST"])
def add_keyword():
    word = request.form["word"].strip().lower()
    try:
        with get_db() as con:
            con.execute("INSERT INTO keywords(word) VALUES(?)", (word,))
        return redirect(url_for("index", msg=f"Keyword '{word}' added!", mt="ok"))
    except Exception:
        return redirect(url_for("index", msg=f"Keyword '{word}' already exists.", mt="err"))


@app.route("/keywords/delete/<int:kid>", methods=["POST"])
def delete_keyword(kid):
    with get_db() as con:
        con.execute("DELETE FROM keywords WHERE id=?", (kid,))
    return redirect(url_for("index"))


@app.route("/settings", methods=["POST"])
def save_settings():
    set_setting("telegram_bot_token", request.form["telegram_bot_token"].strip())
    set_setting("telegram_channel",   request.form["telegram_channel"].strip())
    return redirect(url_for("index", msg="Settings saved!", mt="ok"))


@app.route("/run", methods=["POST"])
def run_now():
    import io, logging
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.INFO)
    logging.getLogger("feedbot").addHandler(handler)

    sent = run_cycle() or 0

    logging.getLogger("feedbot").removeHandler(handler)
    return jsonify({"sent": sent, "log": log_capture.getvalue()})


@app.route("/web_search", methods=["POST"])
def web_search_endpoint():
    """Search web with given keywords, open links, scrape content, send to Telegram."""
    import io, logging
    from flask import jsonify

    data = request.get_json() or {}
    keywords = data.get("keywords", [])
    max_links = data.get("max_links", 10)
    scrape_content = data.get("scrape_content", True)
    send_telegram = data.get("send_telegram", True)
    search_sources_only = data.get("search_sources_only", False)

    # If keywords is a string, split into list
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    if not keywords:
        return jsonify({"error": "No keywords provided", "links": [], "sent_count": 0})

    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.INFO)
    logging.getLogger("web_search").addHandler(handler)
    logging.getLogger("feedbot").addHandler(handler)

    try:
        if search_sources_only:
            # Search through configured sources only
            result = search_sources(
                keywords=keywords,
                max_results=max_links,
                scrape_content=scrape_content,
                send_telegram=send_telegram,
            )
        else:
            # Search the general web
            result = search_scrape_and_send(
                keywords=keywords,
                max_links=max_links,
                scrape_content=scrape_content,
                send_telegram=send_telegram,
            )
        
        log_output = log_capture.getvalue()

        # Extract just the links for display
        links_display = []
        for link in result.get("links", []):
            item = {
                "title": link.get("title", "No title"),
                "url": link.get("url", ""),
            }
            # Include source info if available (for source search)
            if link.get("source"):
                item["source"] = link.get("source")
            links_display.append(item)

        return jsonify({
            "links": links_display,
            "sent_count": result.get("sent_count", 0),
            "total_links": len(links_display),
            "log": log_output,
            "search_type": "sources" if search_sources_only else "web",
        })
    except Exception as e:
        log_output = log_capture.getvalue()
        return jsonify({"error": str(e), "links": [], "sent_count": 0, "log": log_output})


if __name__ == "__main__":
    init_db()
    print("\nFeedBot Dashboard running -> http://localhost:5000\n")
    app.run(debug=True, port=5000)