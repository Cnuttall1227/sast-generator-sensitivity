import os
import sqlite3
import logging
from datetime import datetime

from flask import Flask, g, request
from markupsafe import escape
from urllib.parse import urlencode

DB_PATH = os.environ.get("KB_DB", "/srv/kb/articles.db")
PAGE_SIZE = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kb-search")

app = Flask(__name__)

LAYOUT = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body {{ font-family: sans-serif; max-width: 52rem; margin: 2rem auto; }}
.hit {{ border-bottom: 1px solid #ddd; padding: .75rem 0; }}
.meta {{ color: #666; font-size: .85rem; }}
</style></head>
<body>
<form action="/search" method="get">
  <input name="q" value="{query_value}" placeholder="Search the knowledge base" size="40">
  <button type="submit">Search</button>
</form>
{body}
</body></html>"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def search_articles(query, page):
    pattern = f"%{query}%"
    rows = get_db().execute(
        """SELECT id, title, summary, category, updated_at FROM articles
           WHERE title LIKE ? OR body LIKE ?
           ORDER BY updated_at DESC LIMIT ? OFFSET ?""",
        (pattern, pattern, PAGE_SIZE, (page - 1) * PAGE_SIZE),
    ).fetchall()
    total = get_db().execute(
        "SELECT COUNT(*) FROM articles WHERE title LIKE ? OR body LIKE ?",
        (pattern, pattern),
    ).fetchone()[0]
    return rows, total


def render_hit(row):
    updated = datetime.fromisoformat(row["updated_at"]).strftime("%b %d, %Y")
    return (
        f'<div class="hit"><a href="/articles/{int(row["id"])}">{escape(row["title"])}</a>'
        f'<p>{escape(row["summary"])}</p>'
        f'<p class="meta">{escape(row["category"])} · updated {escape(updated)}</p></div>'
    )


def render_search_results(query, rows, total, page):
    safe_query = escape(query)
    if not rows:
        heading = f"<h2>No articles found for “{safe_query}”</h2>"
        hint = "<p>Try fewer words or check the spelling.</p>"
        return heading + hint
    heading = f"<h2>{total} result{'s' if total != 1 else ''} for “{safe_query}”</h2>"
    hits = "\n".join(render_hit(row) for row in rows)
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    nav = ""
    if pages > 1:
        links = []
        for number in range(1, pages + 1):
            if number == page:
                links.append(f"<strong>{number}</strong>")
            else:
                href = "/search?" + urlencode({"q": query, "page": number})
                links.append(f'<a href="{escape(href)}">{number}</a>')
        nav = f'<p class="pages">{" ".join(links)}</p>'
    return heading + hits + nav


@app.get("/")
def home():
    return LAYOUT.format(title="Knowledge base", query_value="", body="<p>Search for an article above.</p>")


@app.get("/search")
def search():
    query = request.args.get("q", "").strip()[:200]
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    if not query:
        return LAYOUT.format(title="Knowledge base", query_value="", body="<p>Enter a search term.</p>")
    rows, total = search_articles(query, page)
    log.info("Search %r returned %d result(s)", query, total)
    body = render_search_results(query, rows, total, page)
    return LAYOUT.format(title=f"Search: {escape(query)}", query_value=escape(query), body=body)


@app.get("/articles/<int:article_id>")
def article(article_id):
    row = get_db().execute(
        "SELECT title, body, category, updated_at FROM articles WHERE id = ?", (article_id,)
    ).fetchone()
    if row is None:
        return LAYOUT.format(title="Not found", query_value="", body="<h2>Article not found</h2>"), 404
    body = (
        f"<h1>{escape(row['title'])}</h1>"
        f"<p class='meta'>{escape(row['category'])}</p>"
        f"<div>{escape(row['body'])}</div>"
    )
    return LAYOUT.format(title=escape(row["title"]), query_value="", body=body)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))