import os
import json
import sqlite3
import logging
from html import escape
from wsgiref.simple_server import make_server

from pyramid.config import Configurator
from pyramid.httpexceptions import HTTPBadRequest, HTTPNotFound, HTTPUnauthorized
from pyramid.response import Response
from pyramid.view import view_config

DB_PATH = os.environ.get("PORTFOLIO_DB", "/srv/portfolio/portfolio.db")
TOKENS = json.loads(os.environ.get("PORTFOLIO_TOKENS", "{}"))
DEFAULT_ACCENT = "#3366cc"
DEFAULT_FONT = "Georgia, serif"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("portfolio")

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
{theme}
<style>
body {{ font-family: var(--body-font); max-width: 50rem; margin: 2rem auto; }}
h1, a {{ color: var(--accent); }}
.project {{ border-left: 4px solid var(--accent); padding-left: 1rem; margin: 1.5rem 0; }}
</style></head>
<body>
<h1>{name}</h1>
<p>{headline}</p>
{projects}
</body></html>"""


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        conn.executescript(
            """CREATE TABLE IF NOT EXISTS portfolios (
                   username TEXT PRIMARY KEY, name TEXT NOT NULL, headline TEXT NOT NULL,
                   accent TEXT NOT NULL, font TEXT NOT NULL);
               CREATE TABLE IF NOT EXISTS projects (
                   id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL,
                   title TEXT NOT NULL, summary TEXT NOT NULL);"""
        )


def build_theme_css(accent, font):
    return (
        "<style>:root { "
        f"--accent: {accent or DEFAULT_ACCENT}; "
        f"--body-font: {font or DEFAULT_FONT}; "
        "}</style>"
    )


def owner_from_request(request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    username = TOKENS.get(token)
    if not username:
        raise HTTPUnauthorized(json_body={"error": "invalid token"})
    return username


@view_config(route_name="portfolio", request_method="GET")
def portfolio_page(request):
    username = request.matchdict["username"]
    with db() as conn:
        profile = conn.execute("SELECT * FROM portfolios WHERE username = ?", (username,)).fetchone()
        projects = conn.execute(
            "SELECT title, summary FROM projects WHERE username = ? ORDER BY id", (username,)
        ).fetchall()
    if profile is None:
        raise HTTPNotFound()
    project_html = "\n".join(
        f'<div class="project"><h2>{escape(p["title"])}</h2><p>{escape(p["summary"])}</p></div>'
        for p in projects
    ) or "<p>No projects yet.</p>"
    html = PAGE.format(
        title=escape(profile["name"]),
        theme=build_theme_css(profile["accent"], profile["font"]),
        name=escape(profile["name"]),
        headline=escape(profile["headline"]),
        projects=project_html,
    )
    return Response(html, content_type="text/html", charset="utf-8")


@view_config(route_name="settings", request_method="PUT", renderer="json")
def update_settings(request):
    username = owner_from_request(request)
    try:
        data = request.json_body
    except ValueError:
        raise HTTPBadRequest(json_body={"error": "invalid JSON"})
    name = str(data.get("name", "")).strip()[:80]
    headline = str(data.get("headline", "")).strip()[:200]
    accent = str(data.get("accent", DEFAULT_ACCENT)).strip()[:64]
    font = str(data.get("font", DEFAULT_FONT)).strip()[:120]
    if not name:
        raise HTTPBadRequest(json_body={"error": "name is required"})
    with db() as conn:
        conn.execute(
            """INSERT INTO portfolios (username, name, headline, accent, font) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(username) DO UPDATE SET name = excluded.name, headline = excluded.headline,
               accent = excluded.accent, font = excluded.font""",
            (username, name, headline, accent, font),
        )
    log.info("Updated settings for %s", username)
    return {"username": username, "url": f"/u/{username}"}


@view_config(route_name="projects", request_method="POST", renderer="json")
def add_project(request):
    username = owner_from_request(request)
    data = request.json_body if request.body else {}
    title = str(data.get("title", "")).strip()[:120]
    summary = str(data.get("summary", "")).strip()[:1000]
    if not title or not summary:
        raise HTTPBadRequest(json_body={"error": "title and summary are required"})
    with db() as conn:
        cursor = conn.execute(
            "INSERT INTO projects (username, title, summary) VALUES (?, ?, ?)", (username, title, summary)
        )
    request.response.status = 201
    return {"id": cursor.lastrowid}


def create_app():
    init_db()
    with Configurator() as config:
        config.add_route("portfolio", "/u/{username}")
        config.add_route("settings", "/api/settings")
        config.add_route("projects", "/api/projects")
        config.scan()
        return config.make_wsgi_app()


if __name__ == "__main__":
    server = make_server("0.0.0.0", int(os.environ.get("PORT", "6543")), create_app())
    log.info("Portfolio site listening on port %d", server.server_port)
    server.serve_forever()