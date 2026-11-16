import os
import html
import json
import sqlite3
import logging
from datetime import datetime, timezone

from aiohttp import web
from urllib.parse import urlsplit

DB_PATH = os.environ.get("SPEAKERS_DB", "/srv/conf/speakers.db")
EVENT_NAME = os.environ.get("EVENT_NAME", "PyNorth 2026")
ORGANIZER_TOKEN = os.environ.get("ORGANIZER_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("speakers")

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font-family:sans-serif;max-width:60rem;margin:2rem auto}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(16rem,1fr));gap:1rem}}
.card{{border:1px solid #ddd;border-radius:8px;padding:1rem}}
.talk{{font-style:italic}}
</style></head><body>
<h1>{title}</h1>
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
            """CREATE TABLE IF NOT EXISTS speakers (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT NOT NULL,
                   talk_title TEXT NOT NULL,
                   bio TEXT NOT NULL,
                   website TEXT NOT NULL DEFAULT '',
                   approved INTEGER NOT NULL DEFAULT 0,
                   submitted_at TEXT NOT NULL)"""
        )


def safe_website(raw):
    website = raw.strip()
    if not website or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in website):
        return None
    try:
        parts = urlsplit(website)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    return website


def render_profile_card(speaker):
    name = html.escape(speaker["name"])
    talk = html.escape(speaker["talk_title"])
    bio = html.escape(speaker["bio"]).replace("\n", "<br>")
    website = safe_website(speaker["website"])
    link = ""
    if website:
        label = html.escape(website.split("//", 1)[-1].rstrip("/"))
        link = f'<p><a href="{html.escape(website, quote=True)}" rel="noopener nofollow">{label}</a></p>'
    return (
        f'<div class="card"><h2>{name}</h2>'
        f'<p class="talk">{talk}</p>'
        f"<p>{bio}</p>{link}</div>"
    )


def require_organizer(request):
    if not ORGANIZER_TOKEN or request.headers.get("Authorization") != f"Bearer {ORGANIZER_TOKEN}":
        raise web.HTTPUnauthorized(text="organizer token required")


async def lineup(request):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM speakers WHERE approved = 1 ORDER BY name"
        ).fetchall()
    cards = "\n".join(render_profile_card(dict(row)) for row in rows)
    body = f'<div class="grid">{cards}</div>' if rows else "<p>Speakers will be announced soon.</p>"
    return web.Response(text=PAGE.format(title=f"{EVENT_NAME} speakers", body=body), content_type="text/html")


async def submit(request):
    try:
        data = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text="invalid JSON")
    name = str(data.get("name", "")).strip()[:100]
    talk = str(data.get("talk_title", "")).strip()[:200]
    bio = str(data.get("bio", "")).strip()[:2000]
    website = str(data.get("website", "")).strip()[:300]
    if not name or not talk or not bio:
        raise web.HTTPBadRequest(text="name, talk_title and bio are required")
    with db() as conn:
        cursor = conn.execute(
            "INSERT INTO speakers (name, talk_title, bio, website, submitted_at) VALUES (?, ?, ?, ?, ?)",
            (name, talk, bio, website, datetime.now(timezone.utc).isoformat()),
        )
    log.info("New proposal %d from %s", cursor.lastrowid, name)
    return web.json_response({"id": cursor.lastrowid, "status": "submitted"}, status=201)


async def approve(request):
    require_organizer(request)
    speaker_id = int(request.match_info["speaker_id"])
    with db() as conn:
        updated = conn.execute("UPDATE speakers SET approved = 1 WHERE id = ?", (speaker_id,)).rowcount
    if not updated:
        raise web.HTTPNotFound(text="no such proposal")
    return web.json_response({"id": speaker_id, "approved": True})


async def pending(request):
    require_organizer(request)
    with db() as conn:
        rows = conn.execute(
            "SELECT id, name, talk_title, submitted_at FROM speakers WHERE approved = 0 ORDER BY id"
        ).fetchall()
    return web.json_response({"pending": [dict(row) for row in rows]})


def create_app():
    init_db()
    app = web.Application(client_max_size=32 * 1024)
    app.router.add_get("/", lineup)
    app.router.add_post("/proposals", submit)
    app.router.add_get("/proposals/pending", pending)
    app.router.add_post(r"/proposals/{speaker_id:\d+}/approve", approve)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8082")))