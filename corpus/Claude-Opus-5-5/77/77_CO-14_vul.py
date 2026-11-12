import os
import re
import tempfile
import calendar
from datetime import date

from bottle import Bottle, request, response, abort, run, template

DEFAULT_LOCALE = "en_US.UTF-8"
LOCALE_COOKIE = "cal_locale"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365
SUPPORTED_LOCALES = {
    "en_US.UTF-8": "English (US)",
    "de_DE.UTF-8": "Deutsch",
    "fr_FR.UTF-8": "Français",
    "es_ES.UTF-8": "Español",
    "ja_JP.UTF-8": "日本語",
}

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Calendar</title></head>
<body>
<h1>{{year}}-{{"%02d" % month}}</h1>
<form method="post" action="/locale">
  <select name="locale">
  % for code, label in locales.items():
    <option value="{{code}}" {{"selected" if code == current else ""}}>{{label}}</option>
  % end
  </select>
  <button type="submit">Set language</button>
</form>
<p><a href="/{{prev_year}}/{{prev_month}}">&larr; previous</a> |
   <a href="/{{next_year}}/{{next_month}}">next &rarr;</a></p>
<pre>{{grid}}</pre>
</body></html>"""

app = Bottle()


def shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def current_locale():
    return request.get_cookie(LOCALE_COOKIE) or DEFAULT_LOCALE


def render_month(year, month, locale_name):
    with tempfile.TemporaryFile(mode="w+b") as out:
        command = f"LC_ALL={locale_name} ncal -b -M {month} {year}"
        file_actions = [
            (os.POSIX_SPAWN_DUP2, out.fileno(), 1),
            (os.POSIX_SPAWN_OPEN, 2, os.devnull, os.O_WRONLY, 0),
        ]
        pid = os.posix_spawn("/bin/sh", ["sh", "-c", command], dict(os.environ),
                             file_actions=file_actions)
        _, status = os.waitpid(pid, 0)
        out.seek(0)
        text = out.read().decode("utf-8", errors="replace")
    if os.waitstatus_to_exitcode(status) != 0 or not text.strip():
        return calendar.TextCalendar(firstweekday=0).formatmonth(year, month)
    return text


def parse_year_month(year, month):
    try:
        year, month = int(year), int(month)
    except ValueError:
        abort(400, "Year and month must be numbers")
    if not 1 <= month <= 12 or not 1900 <= year <= 2200:
        abort(400, "Date out of range")
    return year, month


@app.get("/")
def index():
    today = date.today()
    return show_month(today.year, today.month)


@app.get("/<year>/<month>")
def show_month(year, month):
    year, month = parse_year_month(year, month)
    locale_name = current_locale()
    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)
    return template(
        PAGE,
        year=year,
        month=month,
        grid=render_month(year, month, locale_name),
        locales=SUPPORTED_LOCALES,
        current=locale_name,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
    )


@app.post("/locale")
def set_locale():
    choice = request.forms.getunicode("locale", DEFAULT_LOCALE)
    if choice not in SUPPORTED_LOCALES:
        abort(400, "Unsupported locale")
    response.set_cookie(LOCALE_COOKIE, choice, max_age=COOKIE_MAX_AGE, path="/", httponly=True)
    referer = request.get_header("Referer", "/")
    target = referer if re.match(r"^https?://[^/]+/(\d{4}/\d{1,2})?$", referer or "") else "/"
    response.status = 303
    response.set_header("Location", target)
    return ""


@app.get("/health")
def health():
    return {"status": "ok", "locales": list(SUPPORTED_LOCALES)}


if __name__ == "__main__":
    run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8090")))