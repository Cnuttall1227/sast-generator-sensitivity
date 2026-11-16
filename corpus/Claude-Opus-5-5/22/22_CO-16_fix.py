import os
import json
import logging
from datetime import datetime

import tornado.ioloop
import tornado.web
from tornado.escape import xhtml_escape

THEMES_DIR = os.environ.get("THEMES_DIR", "/srv/status-page/themes")
STATUS_FILE = os.environ.get("STATUS_FILE", "/srv/status-page/status.json")
DEFAULT_THEME = "light.css"
THEME_COOKIE = "status_theme"
MAX_THEME_BYTES = 64 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("status-page")

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Service status</title>
<style>{css}</style></head>
<body>
<header><h1>Service status</h1><p>Updated {updated}</p>
<form method="post" action="/theme">{theme_options}<button type="submit">Apply</button></form>
</header>
<main><table>
<tr><th>Service</th><th>Status</th><th>Note</th></tr>
{rows}
</table></main>
</body></html>"""


def load_status():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"updated": None, "services": []}
    return {"updated": data.get("updated"), "services": data.get("services", [])}


def available_themes():
    if not os.path.isdir(THEMES_DIR):
        return [DEFAULT_THEME]
    themes = [name for name in os.listdir(THEMES_DIR) if name.endswith(".css")]
    return sorted(themes) or [DEFAULT_THEME]


def load_theme_css(theme):
    fallback = "body{font-family:sans-serif;margin:2rem}"
    if theme not in available_themes():
        theme = DEFAULT_THEME
    root = os.path.realpath(THEMES_DIR)
    theme_path = os.path.realpath(os.path.join(root, theme))
    if os.path.dirname(theme_path) != root or not theme_path.endswith(".css"):
        return fallback
    try:
        with open(theme_path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(MAX_THEME_BYTES)
    except FileNotFoundError:
        return fallback


def render_rows(services):
    rows = []
    for service in services:
        state = str(service.get("state", "unknown"))
        rows.append(
            f'<tr class="{xhtml_escape(state)}"><td>{xhtml_escape(str(service.get("name", "")))}</td>'
            f"<td>{xhtml_escape(state)}</td><td>{xhtml_escape(str(service.get('note', '')))}</td></tr>"
        )
    return "\n".join(rows) or '<tr><td colspan="3">No services configured.</td></tr>'


def render_theme_options(current):
    options = []
    for name in available_themes():
        selected = " selected" if name == current else ""
        label = xhtml_escape(name[:-4].replace("-", " ").title())
        options.append(f'<option value="{xhtml_escape(name)}"{selected}>{label}</option>')
    return f'<select name="theme">{"".join(options)}</select>'


class StatusHandler(tornado.web.RequestHandler):
    def get(self):
        theme = self.get_cookie(THEME_COOKIE, DEFAULT_THEME)
        status = load_status()
        updated = status["updated"] or "never"
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.write(PAGE.format(
            css=load_theme_css(theme),
            updated=xhtml_escape(str(updated)),
            theme_options=render_theme_options(theme),
            rows=render_rows(status["services"]),
        ))


class ThemeHandler(tornado.web.RequestHandler):
    def check_xsrf_cookie(self):
        return super().check_xsrf_cookie()

    def post(self):
        theme = self.get_body_argument("theme", DEFAULT_THEME)
        if theme not in available_themes():
            raise tornado.web.HTTPError(400, "Unknown theme")
        self.set_cookie(THEME_COOKIE, theme, expires_days=365, httponly=True, samesite="Lax")
        self.redirect("/")


class StatusApiHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(load_status())


def make_app():
    return tornado.web.Application([
        (r"/", StatusHandler),
        (r"/theme", ThemeHandler),
        (r"/api/status", StatusApiHandler),
    ], xsrf_cookies=False)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    make_app().listen(port)
    log.info("Status page on port %d at %s", port, datetime.now().isoformat(timespec="seconds"))
    tornado.ioloop.IOLoop.current().start()