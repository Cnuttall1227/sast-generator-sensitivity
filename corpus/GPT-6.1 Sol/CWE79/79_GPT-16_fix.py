from datetime import datetime, timezone
from html import escape
from xml.etree import ElementTree

from flask import Flask, Response, jsonify, request


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4096

SESSIONS = {
    "clay": {
        "title": "Clay Tile Making",
        "room": "Ceramics Studio",
        "minutes": 60,
    },
    "fabric": {
        "title": "Fabric Printing",
        "room": "Textile Room",
        "minutes": 75,
    },
    "paper": {
        "title": "Paper Sculpture",
        "room": "Creative Lab",
        "minutes": 45,
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
        "<header><h1>Maker Festival Exhibit Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/sessions">Sessions</a></nav>'
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


@app.get("/")
def index():
    return html_response(
        "Maker Festival",
        "<h2>Share your creative work</h2>"
        "<p>Browse sessions and preview an exhibit placard.</p>"
        "<p>Submit an XML document to POST /placards/preview.</p>"
        "<pre>&lt;placard&gt;&lt;caption&gt;My project"
        "&lt;/caption&gt;&lt;/placard&gt;</pre>",
    )


@app.get("/sessions")
def list_sessions():
    entries = "".join(
        "<li>"
        f"<strong>{escape(session['title'])}</strong>"
        f" — {escape(session['room'])}"
        f" — {session['minutes']} minutes"
        "</li>"
        for session in SESSIONS.values()
    )
    return html_response(
        "Festival Sessions",
        "<h2>Creative sessions</h2><ul>" + entries + "</ul>",
    )


@app.post("/placards/preview")
def preview_placard():
    try:
        document = ElementTree.fromstring(request.get_data())
    except ElementTree.ParseError:
        return html_response(
            "Invalid Placard",
            "<h2>Expected valid XML.</h2>",
            status=400,
        )

    if document.tag != "placard":
        return html_response(
            "Invalid Placard",
            "<h2>Expected a placard element.</h2>",
            status=400,
        )

    caption = document.findtext("caption", default="").strip()

    if not caption or len(caption) > 300:
        return html_response(
            "Invalid Placard",
            "<h2>Caption must contain 1–300 characters.</h2>",
            status=400,
        )

    body = (
        "<h2>Exhibit placard preview</h2>"
        '<section class="placard">'
        f"<p>{escape(caption)}</p>"
        "<p>Created at the Maker Festival</p>"
        "</section>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response("Exhibit Placard", body)


@app.get("/sessions/<session_id>")
def session_details(session_id):
    session = SESSIONS.get(session_id)

    if session is None:
        return html_response(
            "Not Found",
            "<h2>Session not found.</h2>",
            status=404,
        )

    body = (
        f"<h2>{escape(session['title'])}</h2>"
        f"<p>Room: {escape(session['room'])}</p>"
        f"<p>Duration: {session['minutes']} minutes</p>"
    )
    return html_response("Session Details", body)


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        session_count=len(SESSIONS),
        timestamp=current_time(),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8670, debug=False)
