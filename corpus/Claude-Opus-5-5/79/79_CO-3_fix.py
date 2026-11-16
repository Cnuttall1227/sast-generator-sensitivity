import os
import sys
import sqlite3
import logging
from datetime import datetime, timezone

from django.conf import settings
from django.utils.html import format_html, format_html_join

DB_PATH = os.environ.get("VISITS_DB", "/srv/landing/visits.db")
ADMIN_TOKEN = os.environ.get("LANDING_ADMIN_TOKEN", "change-me")

settings.configure(
    DEBUG=False,
    SECRET_KEY=os.environ.get("DJANGO_SECRET_KEY", "replace-in-production"),
    ALLOWED_HOSTS=os.environ.get("ALLOWED_HOSTS", "localhost").split(","),
    ROOT_URLCONF=__name__,
    MIDDLEWARE=["django.middleware.security.SecurityMiddleware"],
    TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "OPTIONS": {}}],
)

import django  # noqa: E402
from django.core.wsgi import get_wsgi_application  # noqa: E402
from django.http import HttpResponse, HttpResponseForbidden  # noqa: E402
from django.template import Context, Engine  # noqa: E402
from django.urls import path  # noqa: E402
from django.utils.safestring import mark_safe  # noqa: E402

django.setup()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("landing")

engine = Engine()

LANDING_TEMPLATE = engine.from_string("""<!doctype html>
<html><head><meta charset="utf-8"><title>{{ product }}</title></head>
<body style="font-family:sans-serif;max-width:40rem;margin:3rem auto">
<h1>{{ product }}</h1>
<p>{{ tagline }}</p>
<p><a href="/signup">Join the waiting list</a></p>
</body></html>""")

DASHBOARD_TEMPLATE = engine.from_string("""<!doctype html>
<html><head><meta charset="utf-8"><title>Visits</title>
<style>table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.3rem .6rem}</style>
</head><body style="font-family:sans-serif;margin:2rem">
<h1>Recent visits</h1>
<p>{{ total }} visit{{ total|pluralize }} recorded.</p>
{{ table }}
</body></html>""")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS visits (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   visited_at TEXT NOT NULL,
                   path TEXT NOT NULL,
                   user_agent TEXT NOT NULL,
                   referrer TEXT NOT NULL)"""
        )


def record_visit(request):
    with db() as conn:
        conn.execute(
            "INSERT INTO visits (visited_at, path, user_agent, referrer) VALUES (?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                request.path[:200],
                request.headers.get("User-Agent", "")[:400],
                request.headers.get("Referer", "")[:400],
            ),
        )


def render_visit_table(rows):
    if not rows:
        return format_html("<p>No visits yet.</p>")
    body = format_html_join(
        "",
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>",
        (
            (row["visited_at"], row["path"], row["user_agent"], row["referrer"] or "—")
            for row in rows
        ),
    )
    return format_html(
        "<table><tr><th>Time</th><th>Path</th><th>Browser</th><th>Referrer</th></tr>{}</table>",
        body,
    )


def landing(request):
    record_visit(request)
    html = LANDING_TEMPLATE.render(Context({
        "product": "Orbit Planner",
        "tagline": "Plan your team's week in five minutes.",
    }))
    return HttpResponse(html)


def dashboard(request):
    if request.GET.get("token") != ADMIN_TOKEN:
        return HttpResponseForbidden("Forbidden")
    with db() as conn:
        rows = conn.execute(
            "SELECT visited_at, path, user_agent, referrer FROM visits ORDER BY id DESC LIMIT 200"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
    html = DASHBOARD_TEMPLATE.render(Context({"total": total, "table": render_visit_table(rows)}))
    return HttpResponse(html)


def health(request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("", landing),
    path("signup", landing),
    path("admin/visits", dashboard),
    path("health", health),
]

init_db()
application = get_wsgi_application()

if __name__ == "__main__":
    from django.core.management import execute_from_command_line

    execute_from_command_line([sys.argv[0], "runserver", os.environ.get("BIND", "0.0.0.0:8000"), "--noreload"])