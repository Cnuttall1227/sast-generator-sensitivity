from datetime import datetime, timezone
from html import escape

from bottle import Bottle, request, response, run


app = Bottle()

WORKSHOPS = {
    "woodcut": {
        "title": "Woodcut Printmaking",
        "room": "Print Studio",
        "minutes": 90,
    },
    "collage": {
        "title": "Paper Collage",
        "room": "Art Room",
        "minutes": 60,
    },
    "lettering": {
        "title": "Creative Lettering",
        "room": "Design Studio",
        "minutes": 75,
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
        "<header><h1>Community Print Studio</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/workshops">Workshops</a></nav>'
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
        "Print Studio",
        "<h2>Create a workshop poster</h2>"
        "<p>Browse sessions and personalize a poster preview.</p>"
        '<form action="/poster" method="get">'
        '<label>Poster title: <input name="title" maxlength="150"></label>'
        '<button type="submit">Preview poster</button>'
        "</form>",
    )


@app.get("/workshops")
def list_workshops():
    items = "".join(
        "<li>"
        f"<strong>{escape(workshop['title'])}</strong>"
        f" — {escape(workshop['room'])}"
        f" — {workshop['minutes']} minutes"
        "</li>"
        for workshop in WORKSHOPS.values()
    )
    return html_response(
        "Workshops",
        "<h2>Upcoming workshops</h2><ul>" + items + "</ul>",
    )


@app.get("/poster")
def preview_poster():
    title = request.query.getunicode("title", "Creative Workshop")

    if not title.strip() or len(title) > 150:
        return html_response(
            "Invalid Poster",
            "<h2>Poster title must contain 1–150 characters.</h2>",
            status=400,
        )

    body = (
        "<h2>Poster preview</h2>"
        '<section class="poster">'
        '<h3 id="poster-title"></h3>'
        "<p>Join us at the Community Print Studio.</p>"
        "</section>"
        "<script>"
        "const params = new URLSearchParams(window.location.search);"
        "const title = params.get('title') || 'Creative Workshop';"
        "document.getElementById('poster-title').textContent = title;"
        "</script>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response("Poster Preview", body)


@app.get("/health")
def health():
    response.content_type = "application/json"
    return {"status": "ok", "workshop_count": len(WORKSHOPS)}


if __name__ == "__main__":
    run(
        app=app,
        host="127.0.0.1",
        port=8650,
        debug=False,
        reloader=False,
    )
