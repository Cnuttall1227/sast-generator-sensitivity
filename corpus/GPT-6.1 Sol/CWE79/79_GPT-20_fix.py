from datetime import datetime, timezone
from html import escape

from flask import Flask, Response, jsonify, request


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8192

CLUBS = {
    "robotics": {
        "title": "Robotics Club",
        "room": "Engineering Lab",
        "meeting_day": "Tuesday",
    },
    "debate": {
        "title": "Debate Society",
        "room": "Seminar Room",
        "meeting_day": "Wednesday",
    },
    "chess": {
        "title": "Chess Club",
        "room": "Activity Hall",
        "meeting_day": "Thursday",
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
        "<header><h1>Student Club Bookmark Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/clubs">Clubs</a></nav>'
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
        "Club Bookmark Desk",
        "<h2>Keep useful club links together</h2>"
        "<p>Browse clubs and preview a bookmark card.</p>"
        '<form action="/bookmarks/preview" method="post">'
        '<label>Bookmark label: <input name="label" maxlength="100"></label>'
        '<label>Website: <input name="website" maxlength="300"></label>'
        '<button type="submit">Preview bookmark</button>'
        "</form>",
    )


@app.get("/clubs")
def list_clubs():
    entries = "".join(
        "<li>"
        f"<strong>{escape(club['title'])}</strong>"
        f" — {escape(club['room'])}"
        f" — {escape(club['meeting_day'])}"
        "</li>"
        for club in CLUBS.values()
    )
    return html_response(
        "Student Clubs",
        "<h2>Campus clubs</h2><ul>" + entries + "</ul>",
    )


@app.post("/bookmarks/preview")
def preview_bookmark():
    from urllib.parse import urlsplit

    label = request.form.get("label", "").strip()
    website = request.form.get("website", "").strip()

    if not label or len(label) > 100:
        return html_response(
            "Invalid Bookmark",
            "<h2>Label must contain 1–100 characters.</h2>",
            status=400,
        )

    if not website or len(website) > 300:
        return html_response(
            "Invalid Bookmark",
            "<h2>Website must contain 1–300 characters.</h2>",
            status=400,
        )

    try:
        if any(ord(character) <= 32 or ord(character) == 127 for character in website):
            raise ValueError("Invalid URL characters.")

        parsed = urlsplit(website)

        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            raise ValueError("Expected an HTTP or HTTPS URL.")

        if parsed.username is not None or parsed.password is not None:
            raise ValueError("URL credentials are not supported.")

        parsed.port
    except ValueError:
        return html_response(
            "Invalid Bookmark",
            "<h2>Enter a valid HTTP or HTTPS website URL.</h2>",
            status=400,
        )

    body = (
        "<h2>Bookmark preview</h2>"
        '<section class="bookmark">'
        f'<a href="{escape(website, quote=True)}">{escape(label)}</a>'
        "</section>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response("Bookmark Preview", body)


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        club_count=len(CLUBS),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8710, debug=False)
