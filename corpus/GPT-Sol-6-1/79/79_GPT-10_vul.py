from datetime import datetime, timezone
from html import escape
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server


EXHIBITS = {
    "radio": {
        "title": "Early Radio Workshop",
        "room": "Communications Hall",
        "minutes": 25,
    },
    "printing": {
        "title": "Printing Press Demonstration",
        "room": "Industrial Gallery",
        "minutes": 30,
    },
    "clocks": {
        "title": "Mechanical Clock Collection",
        "room": "Timekeeping Room",
        "minutes": 20,
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
        "<header><h1>Technology Heritage Visitor Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/exhibits">Exhibits</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


def respond(start_response, title, body, status="200 OK"):
    content = page(title, body).encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(content))),
            ("X-Content-Type-Options", "nosniff"),
        ],
    )
    return [content]


def index(start_response):
    return respond(
        start_response,
        "Visitor Desk",
        "<h2>Discover historic technology</h2>"
        "<p>Browse exhibits or preview a visitor message.</p>"
        '<p><a href="/message">Preview visitor message</a></p>',
    )


def list_exhibits(start_response):
    items = "".join(
        "<li>"
        f"<strong>{escape(exhibit['title'])}</strong>"
        f" — {escape(exhibit['room'])}"
        f" — {exhibit['minutes']} minutes"
        "</li>"
        for exhibit in EXHIBITS.values()
    )
    return respond(
        start_response,
        "Exhibits",
        "<h2>Exhibits</h2><ul>" + items + "</ul>",
    )


def preview_message(environ, start_response):
    referer = environ.get("HTTP_REFERER", "")
    _, separator, query = referer.partition("?")
    parameters = parse_qs(query if separator else "", max_num_fields=20)
    message = parameters.get("visitor_message", ["Enjoy your visit!"])[0]

    if not message.strip() or len(message) > 200:
        return respond(
            start_response,
            "Invalid Message",
            "<h2>Message must contain 1–200 characters.</h2>",
            "400 Bad Request",
        )

    # CWE-79: a parameter from the Referer URL is reflected into HTML.
    body = (
        "<h2>Visitor message preview</h2>"
        f"<p>{message}</p>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return respond(start_response, "Visitor Message", body)


def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/")

    if method != "GET":
        return respond(
            start_response,
            "Method Not Allowed",
            "<h2>Only GET requests are supported.</h2>",
            "405 Method Not Allowed",
        )

    if path == "/":
        return index(start_response)

    if path == "/exhibits":
        return list_exhibits(start_response)

    if path == "/message":
        return preview_message(environ, start_response)

    return respond(
        start_response,
        "Not Found",
        "<h2>Page not found</h2>",
        "404 Not Found",
    )


if __name__ == "__main__":
    with make_server("127.0.0.1", 8610, application) as server:
        server.serve_forever()
