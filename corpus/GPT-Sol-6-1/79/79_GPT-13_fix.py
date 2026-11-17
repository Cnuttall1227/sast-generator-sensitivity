import json
from datetime import datetime, timezone
from html import escape

from werkzeug.serving import run_simple
from werkzeug.wrappers import Request, Response


DISPLAYS = {
    "entrance": {
        "name": "Entrance Display",
        "location": "Main Doors",
        "orientation": "landscape",
    },
    "reading": {
        "name": "Reading Room Display",
        "location": "Second Floor",
        "orientation": "portrait",
    },
    "children": {
        "name": "Children's Display",
        "location": "Family Wing",
        "orientation": "landscape",
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
        "<header><h1>Library Announcement Display Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/displays">Displays</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


def html_response(title, body, status=200):
    return Response(
        page(title, body),
        status=status,
        content_type="text/html; charset=utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def index():
    return html_response(
        "Announcement Desk",
        "<h2>Prepare library announcements</h2>"
        "<p>Browse displays or preview an announcement heading.</p>"
        "<p>Send a UTF-8 text body with PUT /announcements/preview.</p>",
    )


def list_displays():
    items = "".join(
        "<li>"
        f"<strong>{escape(display['name'])}</strong>"
        f" — {escape(display['location'])}"
        f" — {escape(display['orientation'])}"
        "</li>"
        for display in DISPLAYS.values()
    )
    return html_response(
        "Displays",
        "<h2>Available displays</h2><ul>" + items + "</ul>",
    )


def preview_announcement(request):
    raw_body = request.get_data()

    if len(raw_body) > 1024:
        return html_response(
            "Invalid Announcement",
            "<h2>Announcement body is too large.</h2>",
            status=413,
        )

    try:
        heading = raw_body.decode("utf-8").strip()
    except UnicodeDecodeError:
        return html_response(
            "Invalid Announcement",
            "<h2>Announcement must be UTF-8 text.</h2>",
            status=400,
        )

    if not heading or len(heading) > 200:
        return html_response(
            "Invalid Announcement",
            "<h2>Heading must contain 1–200 characters.</h2>",
            status=400,
        )

    body = (
        "<h2>Announcement preview</h2>"
        '<section class="announcement">'
        f"<h3>{escape(heading)}</h3>"
        "<p>Visit the information desk for details.</p>"
        "</section>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response("Announcement Preview", body)


@Request.application
def application(request):
    request.max_content_length = 4096

    if request.method == "GET" and request.path == "/":
        return index()

    if request.method == "GET" and request.path == "/displays":
        return list_displays()

    if request.method == "PUT" and request.path == "/announcements/preview":
        return preview_announcement(request)

    if request.method == "GET" and request.path == "/health":
        return Response(
            json.dumps({"status": "ok", "display_count": len(DISPLAYS)}),
            content_type="application/json",
        )

    return html_response("Not Found", "<h2>Page not found</h2>", status=404)


if __name__ == "__main__":
    run_simple(
        "127.0.0.1",
        8640,
        application,
        use_debugger=False,
        use_reloader=False,
    )
