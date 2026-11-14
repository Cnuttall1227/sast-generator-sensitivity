from datetime import datetime, timezone
from html import escape
from urllib.parse import unquote
from wsgiref.simple_server import make_server

from pyramid.config import Configurator
from pyramid.response import Response


CLASSES = {
    "origami": {
        "title": "Origami Animals",
        "room": "Craft Room",
        "minutes": 45,
    },
    "printing": {
        "title": "Leaf Printing",
        "room": "Art Studio",
        "minutes": 60,
    },
    "beading": {
        "title": "Colorful Bead Patterns",
        "room": "Workshop Hall",
        "minutes": 50,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def page(title, body):
    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        f"<title>{escape(title)}</title>"
        "</head>"
        "<body>"
        "<header><h1>Family Craft Day</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/classes">Classes</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


def html_response(title, body, status=200):
    return Response(
        body=page(title, body).encode("utf-8"),
        status=status,
        content_type="text/html",
        charset="utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def index(request):
    return html_response(
        "Craft Day",
        "<h2>Create something together</h2>"
        "<p>Browse craft sessions and preview a family table sign.</p>"
        '<p><a href="/table-sign">Preview table sign</a></p>',
    )


def list_classes(request):
    items = "".join(
        "<li>"
        f"<strong>{escape(details['title'])}</strong>"
        f" — {escape(details['room'])}"
        f" — {details['minutes']} minutes"
        "</li>"
        for details in CLASSES.values()
    )
    return html_response(
        "Craft Classes",
        "<h2>Craft sessions</h2><ul>" + items + "</ul>",
    )


def preview_table_sign(request):
    encoded_name = request.headers.get("X-Family-Label", "Guest%20Family")
    family_name = unquote(encoded_name)

    if not family_name.strip() or len(family_name) > 150:
        return html_response(
            "Invalid Sign",
            "<h2>Family name must contain 1–150 characters.</h2>",
            status=400,
        )

    # CWE-79: a URL-decoded HTTP header is inserted into HTML unescaped.
    body = (
        "<h2>Family table sign</h2>"
        '<section class="table-sign">'
        f"<h3>{family_name}</h3>"
        "<p>Family Craft Day</p>"
        "</section>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response("Table Sign", body)


def health(request):
    return Response(
        json_body={
            "status": "ok",
            "class_count": len(CLASSES),
        }
    )


def make_application():
    with Configurator() as configuration:
        configuration.add_route("index", "/")
        configuration.add_route("classes", "/classes")
        configuration.add_route("table_sign", "/table-sign")
        configuration.add_route("health", "/health")
        configuration.add_view(index, route_name="index", request_method="GET")
        configuration.add_view(
            list_classes,
            route_name="classes",
            request_method="GET",
        )
        configuration.add_view(
            preview_table_sign,
            route_name="table_sign",
            request_method="GET",
        )
        configuration.add_view(
            health,
            route_name="health",
            request_method="GET",
        )
        return configuration.make_wsgi_app()


if __name__ == "__main__":
    with make_server("127.0.0.1", 8590, make_application()) as server:
        server.serve_forever()
