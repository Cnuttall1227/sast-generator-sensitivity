import os
import json
import logging
from datetime import date, datetime, timedelta

import tornado.ioloop
import tornado.web
from tornado.escape import xhtml_escape

DATA_FILE = os.environ.get("TIDE_DATA", "/srv/tides/tides.json")
SITE_NAME = os.environ.get("SITE_NAME", "Harbor Tides")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tides")

LAYOUT = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title} – {site}</title>
<style>body{{font-family:sans-serif;max-width:44rem;margin:2rem auto}}
table{{border-collapse:collapse}}td,th{{padding:.3rem .8rem;border-bottom:1px solid #ddd}}</style>
</head><body>
<p><a href="/">{site}</a></p>
{body}
</body></html>"""


def load_stations():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle).get("stations", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def page(title, body):
    return LAYOUT.format(title=xhtml_escape(title), site=xhtml_escape(SITE_NAME), body=body)


class BaseHandler(tornado.web.RequestHandler):
    def write_error(self, status_code, **kwargs):
        reason = self._reason or "Error"
        if status_code == 404:
            body = (
                f"<h1>Page not found</h1>"
                f"<p>We couldn't find <code>{self.request.uri}</code>.</p>"
                f'<p><a href="/">Back to the station list</a></p>'
            )
        else:
            body = f"<h1>{xhtml_escape(str(status_code))} {xhtml_escape(reason)}</h1>"
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.finish(page(reason, body))


class StationListHandler(BaseHandler):
    def get(self):
        stations = load_stations()
        items = "".join(
            f'<li><a href="/stations/{xhtml_escape(sid)}">{xhtml_escape(info.get("name", sid))}</a></li>'
            for sid, info in sorted(stations.items())
        )
        body = f"<h1>Tide stations</h1><ul>{items or '<li>No stations configured.</li>'}</ul>"
        self.write(page("Stations", body))


class StationHandler(BaseHandler):
    def get(self, station_id):
        stations = load_stations()
        station = stations.get(station_id)
        if station is None:
            raise tornado.web.HTTPError(404)
        day_param = self.get_argument("day", date.today().isoformat())
        try:
            day = date.fromisoformat(day_param)
        except ValueError:
            raise tornado.web.HTTPError(400, reason="Invalid date")
        events = [e for e in station.get("events", []) if e.get("time", "").startswith(day.isoformat())]
        rows = "".join(
            f"<tr><td>{xhtml_escape(e['time'][11:16])}</td>"
            f"<td>{xhtml_escape(e.get('type', ''))}</td>"
            f"<td>{float(e.get('height_m', 0)):.2f} m</td></tr>"
            for e in sorted(events, key=lambda e: e["time"])
        )
        prev_day = (day - timedelta(days=1)).isoformat()
        next_day = (day + timedelta(days=1)).isoformat()
        safe_id = xhtml_escape(station_id)
        body = (
            f"<h1>{xhtml_escape(station.get('name', station_id))}</h1>"
            f"<p>{day:%A %d %B %Y}</p>"
            f'<p><a href="/stations/{safe_id}?day={prev_day}">← previous</a> | '
            f'<a href="/stations/{safe_id}?day={next_day}">next →</a></p>'
            f"<table><tr><th>Time</th><th>Tide</th><th>Height</th></tr>"
            f"{rows or '<tr><td colspan=3>No predictions for this day.</td></tr>'}</table>"
        )
        self.write(page(station.get("name", station_id), body))


class StationApiHandler(BaseHandler):
    def get(self, station_id):
        station = load_stations().get(station_id)
        if station is None:
            raise tornado.web.HTTPError(404)
        self.write({"id": station_id, "name": station.get("name"), "events": station.get("events", [])})


class NotFoundHandler(BaseHandler):
    def prepare(self):
        raise tornado.web.HTTPError(404)


class HealthHandler(BaseHandler):
    def get(self):
        self.write({"status": "ok", "time": datetime.utcnow().isoformat()})


def make_app():
    return tornado.web.Application(
        [
            (r"/", StationListHandler),
            (r"/stations/([A-Za-z0-9_-]+)", StationHandler),
            (r"/api/stations/([A-Za-z0-9_-]+)", StationApiHandler),
            (r"/health", HealthHandler),
        ],
        default_handler_class=NotFoundHandler,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8888"))
    make_app().listen(port)
    log.info("%s listening on port %d", SITE_NAME, port)
    tornado.ioloop.IOLoop.current().start()