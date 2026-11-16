import os
import json
import sqlite3
import logging
import nh3
from datetime import datetime, timezone
from html import escape
from wsgiref.simple_server import make_server

import falcon
import markdown

DB_PATH = os.environ.get("CHANGELOG_DB", "/srv/changelog/changelog.db")
PRODUCT = os.environ.get("CHANGELOG_PRODUCT", "Ledgerline")
PUBLISH_TOKENS = set(filter(None, os.environ.get("CHANGELOG_TOKENS", "").split(",")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("changelog")

ALLOWED_TAGS = {
    "p", "br", "hr", "h3", "h4", "h5", "h6", "strong", "em", "del", "code", "pre",
    "blockquote", "ul", "ol", "li", "a", "table", "thead", "tbody", "tr", "th", "td",
}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "code": {"class"},
    "th": {"align"},
    "td": {"align"},
}

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:sans-serif;max-width:46rem;margin:2rem auto;line-height:1.5}}
.release{{border-bottom:1px solid #eee;padding:1rem 0}}.date{{color:#777}}</style>
</head><body>
<h1>{heading}</h1>
{body}
</body></html>"""


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS releases (
                   version TEXT PRIMARY KEY,
                   notes TEXT NOT NULL,
                   author TEXT NOT NULL,
                   published_at TEXT NOT NULL)"""
        )


def render_notes(notes):
    html = markdown.markdown(notes, extensions=["fenced_code", "tables", "sane_lists"])
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer nofollow",
    )


def render_release(row):
    published = datetime.fromisoformat(row["published_at"]).strftime("%d %b %Y")
    return (
        f'<section class="release" id="v{escape(row["version"])}">'
        f'<h2>{escape(PRODUCT)} {escape(row["version"])}</h2>'
        f'<p class="date">{escape(published)} · {escape(row["author"])}</p>'
        f"{render_notes(row['notes'])}</section>"
    )


class AuthMiddleware:
    def process_resource(self, req, resp, resource, params):
        if req.method in ("POST", "DELETE"):
            token = (req.get_header("Authorization") or "").removeprefix("Bearer ")
            if not PUBLISH_TOKENS or token not in PUBLISH_TOKENS:
                raise falcon.HTTPUnauthorized(title="Publishing token required")


class ChangelogPage:
    def on_get(self, req, resp):
        with db() as conn:
            rows = conn.execute("SELECT * FROM releases ORDER BY published_at DESC LIMIT 50").fetchall()
        body = "\n".join(render_release(r) for r in rows) or "<p>No releases yet.</p>"
        resp.content_type = falcon.MEDIA_HTML
        resp.text = PAGE.format(title=f"{escape(PRODUCT)} changelog", heading=f"{escape(PRODUCT)} changelog", body=body)


class ReleaseCollection:
    def on_get(self, req, resp):
        with db() as conn:
            rows = conn.execute("SELECT version, author, published_at FROM releases ORDER BY published_at DESC").fetchall()
        resp.media = {"releases": [dict(r) for r in rows]}

    def on_post(self, req, resp):
        data = req.get_media(default_when_empty={}) or {}
        version = str(data.get("version", "")).strip()[:32]
        notes = str(data.get("notes", "")).strip()[:20000]
        author = str(data.get("author", "")).strip()[:80]
        if not version or not notes or not author:
            raise falcon.HTTPBadRequest(title="version, notes and author are required")
        if not all(c.isalnum() or c in ".-+" for c in version):
            raise falcon.HTTPBadRequest(title="version may contain letters, digits, '.', '-' and '+'")
        try:
            with db() as conn:
                conn.execute(
                    "INSERT INTO releases (version, notes, author, published_at) VALUES (?, ?, ?, ?)",
                    (version, notes, author, datetime.now(timezone.utc).isoformat()),
                )
        except sqlite3.IntegrityError:
            raise falcon.HTTPConflict(title=f"Release {version} already exists")
        log.info("Published %s by %s", version, author)
        resp.status = falcon.HTTP_201
        resp.media = {"version": version, "url": f"/#v{version}"}


class ReleaseItem:
    def on_get(self, req, resp, version):
        with db() as conn:
            row = conn.execute("SELECT * FROM releases WHERE version = ?", (version,)).fetchone()
        if row is None:
            raise falcon.HTTPNotFound()
        resp.media = dict(row)

    def on_delete(self, req, resp, version):
        with db() as conn:
            deleted = conn.execute("DELETE FROM releases WHERE version = ?", (version,)).rowcount
        if not deleted:
            raise falcon.HTTPNotFound()
        resp.media = {"deleted": version}


def create_app():
    init_db()
    app = falcon.App(middleware=[AuthMiddleware()])
    app.add_route("/", ChangelogPage())
    app.add_route("/api/releases", ReleaseCollection())
    app.add_route("/api/releases/{version}", ReleaseItem())
    return app


app = create_app()

if __name__ == "__main__":
    with make_server("0.0.0.0", int(os.environ.get("PORT", "8060")), app) as server:
        log.info("Changelog listening on port %d", server.server_port)
        server.serve_forever()