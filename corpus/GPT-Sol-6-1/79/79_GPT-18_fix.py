import json
from datetime import datetime, timezone
from html import escape

from bottle import Bottle, request, response, run


app = Bottle()

TEAMS = {
    "sorting": {
        "title": "Donation Sorting",
        "location": "Warehouse A",
        "capacity": 12,
    },
    "packing": {
        "title": "Food Parcel Packing",
        "location": "Community Kitchen",
        "capacity": 18,
    },
    "delivery": {
        "title": "Neighborhood Delivery",
        "location": "Loading Bay",
        "capacity": 8,
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
        "<header><h1>Community Food Bank Volunteer Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/teams">Teams</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


def html_response(title, body, status=200):
    response.status = status
    response.content_type = "text/html; charset=utf-8"
    response.set_header("X-Content-Type-Options", "nosniff")
    return page(title, body)


@app.get("/")
def index():
    return html_response(
        "Volunteer Desk",
        "<h2>Help your neighbors</h2>"
        "<p>Browse teams and preview a volunteer briefing card.</p>"
        "<p>POST a JSON array containing a volunteer name to /briefing.</p>",
    )


@app.get("/teams")
def list_teams():
    entries = "".join(
        "<li>"
        f"<strong>{escape(team['title'])}</strong>"
        f" — {escape(team['location'])}"
        f" — Capacity: {team['capacity']}"
        "</li>"
        for team in TEAMS.values()
    )
    return html_response(
        "Volunteer Teams",
        "<h2>Available teams</h2><ul>" + entries + "</ul>",
    )


@app.post("/briefing")
def preview_briefing():
    raw_body = request.body.read(4097)

    if len(raw_body) > 4096:
        return html_response(
            "Invalid Briefing",
            "<h2>Request body is too large.</h2>",
            status=413,
        )

    try:
        selection = json.loads(raw_body)
    except (ValueError, UnicodeError, RecursionError):
        return html_response(
            "Invalid Briefing",
            "<h2>Expected valid JSON.</h2>",
            status=400,
        )

    if (
        not isinstance(selection, list)
        or len(selection) != 2
        or selection[0] != "volunteer"
    ):
        return html_response(
            "Invalid Briefing",
            "<h2>Expected a two-element volunteer selection array.</h2>",
            status=400,
        )

    volunteer = selection[1]

    if not isinstance(volunteer, str) or not 1 <= len(volunteer.strip()) <= 120:
        return html_response(
            "Invalid Briefing",
            "<h2>Volunteer name must contain 1–120 characters.</h2>",
            status=400,
        )

    body = (
        "<h2>Volunteer briefing</h2>"
        f"<p>Today's volunteer: <strong>{escape(volunteer)}</strong></p>"
        "<p>Check in with your team coordinator before beginning.</p>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response("Briefing Card", body)


@app.get("/health")
def health():
    response.content_type = "application/json"
    return {"status": "ok", "team_count": len(TEAMS)}


if __name__ == "__main__":
    run(
        app=app,
        host="127.0.0.1",
        port=8690,
        debug=False,
        reloader=False,
    )
