from datetime import datetime, timezone
from html import escape
from wsgiref.simple_server import make_server

from bottle import Bottle, request, response


app = Bottle()

ROUTES = {
    "river": {
        "name": "Riverfront Architecture Walk",
        "minutes": 75,
        "meeting_point": "Visitor Center",
    },
    "market": {
        "name": "Historic Market Walk",
        "minutes": 60,
        "meeting_point": "Market Clock",
    },
    "gardens": {
        "name": "Public Gardens Walk",
        "minutes": 90,
        "meeting_point": "East Gate",
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def html_response(content, status=200):
    response.status = status
    response.content_type = "text/html; charset=utf-8"
    response.set_header("X-Content-Type-Options", "nosniff")
    return content


def page(title, body):
    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        f"<title>{escape(title)}</title>"
        "</head>"
        "<body>"
        "<header><h1>Neighborhood Walking Tour Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/routes">Routes</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


@app.get("/")
def index():
    body = (
        "<h2>Plan a walking tour</h2>"
        "<p>Browse routes and create a welcome card for your group.</p>"
        '<form action="/welcome" method="post">'
        '<label>Group name: <input name="group_name" maxlength="200"></label>'
        '<button type="submit">Preview welcome card</button>'
        "</form>"
    )
    return html_response(page("Walking Tour Desk", body))


@app.get("/routes")
def list_routes():
    items = []

    for route_id, details in ROUTES.items():
        items.append(
            "<li>"
            f"<strong>{escape(details['name'])}</strong>"
            f" — {details['minutes']} minutes"
            f" — Meet at {escape(details['meeting_point'])}"
            f' — <a href="/routes/{escape(route_id, quote=True)}">Details</a>'
            "</li>"
        )

    return html_response(
        page("Walking Routes", "<h2>Routes</h2><ul>" + "".join(items) + "</ul>")
    )


@app.get("/routes/<route_id>")
def route_details(route_id):
    details = ROUTES.get(route_id)

    if details is None:
        return html_response(
            page("Not Found", "<h2>Route not found</h2>"),
            status=404,
        )

    body = (
        f"<h2>{escape(details['name'])}</h2>"
        f"<p>Duration: {details['minutes']} minutes</p>"
        f"<p>Meeting point: {escape(details['meeting_point'])}</p>"
    )
    return html_response(page(details["name"], body))


@app.post("/welcome")
def preview_welcome():
    group_name = request.forms.getunicode("group_name", "").strip()

    if not group_name or len(group_name) > 200:
        return html_response(
            page("Invalid Group", "<h2>Enter a group name of 1–200 characters.</h2>"),
            status=400,
        )

    body = (
        "<h2>Group welcome card</h2>"
        f"<p>Welcome, {escape(group_name)}!</p>"
        "<p>Your walking tour guide will meet you at the selected route.</p>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response(page("Welcome Card", body))


@app.get("/health")
def health():
    response.content_type = "application/json"
    return {"status": "ok", "route_count": len(ROUTES)}


if __name__ == "__main__":
    with make_server("127.0.0.1", 8520, app) as server:
        server.serve_forever()
