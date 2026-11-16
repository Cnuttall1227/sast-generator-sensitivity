import os
import re
import html
import sqlite3
import logging
from datetime import datetime, timezone

import cherrypy

DB_PATH = os.environ.get("RSVP_DB", "/srv/rsvp/rsvp.db")
EVENT_TITLE = os.environ.get("EVENT_TITLE", "Riverside Volunteer Day")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SHIFT_OPTIONS = {"morning": "Morning (8–12)", "afternoon": "Afternoon (12–4)", "both": "Both shifts"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rsvp")

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:sans-serif;max-width:34rem;margin:2rem auto}}
label{{display:block;margin-top:.75rem}}.errors{{color:#b00}}</style>
</head><body>
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
            """CREATE TABLE IF NOT EXISTS rsvps (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                   phone TEXT, shift TEXT NOT NULL, created_at TEXT NOT NULL)"""
        )


def validate(form):
    errors = []
    if not form["name"]:
        errors.append("Please tell us your name.")
    if not EMAIL_PATTERN.match(form["email"]):
        errors.append("Please enter a valid email address.")
    if form["phone"] and not re.fullmatch(r"[0-9 +()-]{7,20}", form["phone"]):
        errors.append("Phone numbers may only contain digits, spaces and + ( ) -.")
    if form["shift"] not in SHIFT_OPTIONS:
        errors.append("Please choose a shift.")
    return errors


def render_form(values, errors):
    error_html = ""
    if errors:
        items = "".join(f"<li>{html.escape(e)}</li>" for e in errors)
        error_html = f'<ul class="errors">{items}</ul>'
    options = "".join(
        f'<option value="{key}"{" selected" if values.get("shift") == key else ""}>{label}</option>'
        for key, label in SHIFT_OPTIONS.items()
    )
    name = html.escape(values.get("name", ""), quote=False)
    email = html.escape(values.get("email", ""), quote=False)
    phone = html.escape(values.get("phone", ""), quote=False)
    return (
        f"{error_html}"
        f'<form method="post" action="/rsvp">'
        f'<label>Name <input name="name" value="{name}" maxlength="80"></label>'
        f'<label>Email <input name="email" type="email" value="{email}" maxlength="254"></label>'
        f'<label>Phone (optional) <input name="phone" value="{phone}" maxlength="20"></label>'
        f'<label>Shift <select name="shift"><option value="">Choose…</option>{options}</select></label>'
        f'<p><button type="submit">Count me in</button></p></form>'
    )


class RsvpApp:
    @cherrypy.expose
    def index(self):
        return PAGE.format(title=html.escape(EVENT_TITLE), body=render_form({}, []))

    @cherrypy.expose
    def rsvp(self, name="", email="", phone="", shift="", **_ignored):
        if cherrypy.request.method != "POST":
            raise cherrypy.HTTPRedirect("/")
        form = {
            "name": name.strip()[:80],
            "email": email.strip().lower()[:254],
            "phone": phone.strip()[:20],
            "shift": shift.strip(),
        }
        errors = validate(form)
        if not errors:
            try:
                with db() as conn:
                    conn.execute(
                        "INSERT INTO rsvps (name, email, phone, shift, created_at) VALUES (?, ?, ?, ?, ?)",
                        (form["name"], form["email"], form["phone"] or None, form["shift"],
                         datetime.now(timezone.utc).isoformat()),
                    )
            except sqlite3.IntegrityError:
                errors.append("That email address has already signed up.")
        if errors:
            cherrypy.response.status = 400
            return PAGE.format(title=html.escape(EVENT_TITLE), body=render_form(form, errors))
        log.info("New RSVP for %s shift", form["shift"])
        raise cherrypy.HTTPRedirect("/thanks", status=303)

    @cherrypy.expose
    def thanks(self):
        body = "<p>Thanks for signing up! We'll email you the details closer to the day.</p>"
        return PAGE.format(title=html.escape(EVENT_TITLE), body=body)

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def health(self):
        with db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM rsvps").fetchone()[0]
        return {"status": "ok", "rsvps": count}


if __name__ == "__main__":
    init_db()
    cherrypy.config.update({
        "server.socket_host": "0.0.0.0",
        "server.socket_port": int(os.environ.get("PORT", "8070")),
    })
    cherrypy.quickstart(RsvpApp(), "/")