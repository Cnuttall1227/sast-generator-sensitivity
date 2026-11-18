import os
import json
import logging
from html import escape
from wsgiref.simple_server import make_server

from chameleon import PageTemplate
from pyramid.config import Configurator
from pyramid.httpexceptions import HTTPBadRequest, HTTPNotFound, HTTPUnauthorized
from pyramid.response import Response
from pyramid.view import view_config

LAYOUT_FILE = os.environ.get("BADGE_LAYOUTS", "/srv/badges/layouts.json")
ORGANIZER_TOKENS = json.loads(os.environ.get("BADGE_ORGANIZER_TOKENS", "{}"))
MAX_LAYOUT_LENGTH = 4000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("badge-studio")

DEFAULT_LAYOUT = """<div class="badge">
  <h1 tal:content="attendee/name">Name</h1>
  <p class="org" tal:content="attendee/company">Company</p>
  <p class="type" tal:content="attendee/ticket_type">General</p>
</div>"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Badge preview – {event}</title>
<style>
.badge {{ width: 4in; height: 3in; border: 1px solid #333; border-radius: 8px; padding: .3in;
          font-family: sans-serif; text-align: center; box-sizing: border-box; }}
.badge h1 {{ font-size: 28pt; margin: .2in 0 .1in; }} .org {{ font-size: 14pt; }}
.type {{ margin-top: .3in; text-transform: uppercase; letter-spacing: .1em; }}
</style></head><body>{badge}</body></html>"""

SAMPLE_ATTENDEE = {"name": "Jordan Rivera", "company": "Lakeside Robotics", "ticket_type": "Speaker", "pronouns": "they/them"}


def load_layouts():
    try:
        with open(LAYOUT_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_layouts(layouts):
    os.makedirs(os.path.dirname(LAYOUT_FILE), exist_ok=True)
    with open(LAYOUT_FILE, "w", encoding="utf-8") as handle:
        json.dump(layouts, handle, indent=2)


def organizer_event(request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    event = ORGANIZER_TOKENS.get(token)
    if not event:
        raise HTTPUnauthorized(json_body={"error": "organizer token required"})
    return event


def render_badge(layout_source, attendee, event_name):
    template = PageTemplate(layout_source)
    return template(attendee=attendee, event=event_name)


@view_config(route_name="layout", request_method="GET", renderer="json")
def get_layout(request):
    event = organizer_event(request)
    return {"event": event, "layout": load_layouts().get(event, DEFAULT_LAYOUT)}


@view_config(route_name="layout", request_method="PUT", renderer="json")
def put_layout(request):
    event = organizer_event(request)
    try:
        layout = str(request.json_body.get("layout", "")).strip()
    except ValueError:
        raise HTTPBadRequest(json_body={"error": "invalid JSON"})
    if not layout or len(layout) > MAX_LAYOUT_LENGTH:
        raise HTTPBadRequest(json_body={"error": f"layout must be 1-{MAX_LAYOUT_LENGTH} characters"})
    try:
        render_badge(layout, SAMPLE_ATTENDEE, event)
    except Exception as exc:
        raise HTTPBadRequest(json_body={"error": f"layout failed to render: {type(exc).__name__}"})
    layouts = load_layouts()
    layouts[event] = layout
    save_layouts(layouts)
    log.info("Organizer for %s updated badge layout", event)
    return {"saved": True}


@view_config(route_name="preview", request_method="GET")
def preview(request):
    event = organizer_event(request)
    layout = load_layouts().get(event, DEFAULT_LAYOUT)
    attendee = dict(SAMPLE_ATTENDEE)
    for field in ("name", "company", "ticket_type"):
        if request.params.get(field):
            attendee[field] = request.params[field][:80]
    try:
        badge = render_badge(layout, attendee, event)
    except Exception:
        log.exception("Badge render failed for %s", event)
        badge = render_badge(DEFAULT_LAYOUT, attendee, event)
    return Response(PAGE.format(event=escape(event), badge=badge), content_type="text/html", charset="utf-8")


@view_config(route_name="health", renderer="json")
def health(request):
    return {"status": "ok"}


def create_app():
    with Configurator() as config:
        config.add_route("layout", "/layout")
        config.add_route("preview", "/preview")
        config.add_route("health", "/health")
        config.scan()
        return config.make_wsgi_app()


if __name__ == "__main__":
    server = make_server("127.0.0.1", int(os.environ.get("PORT", "6543")), create_app())
    log.info("Badge studio listening on port %d", server.server_port)
    server.serve_forever()