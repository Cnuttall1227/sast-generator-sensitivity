from datetime import datetime, timezone
from html import escape

from sanic import Sanic
from sanic.response import html, json


app = Sanic("CommunityChoirProgramDesk")

CONCERTS = {
    "spring": {
        "title": "Spring Voices",
        "venue": "Community Hall",
        "minutes": 75,
    },
    "summer": {
        "title": "Songs in the Park",
        "venue": "Riverside Pavilion",
        "minutes": 60,
    },
    "winter": {
        "title": "Winter Harmonies",
        "venue": "Arts Center",
        "minutes": 90,
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
        "<header><h1>Community Choir Program Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/concerts">Concerts</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


def html_response(title, body, status=200):
    return html(
        page(title, body),
        status=status,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/")
async def index(request):
    return html_response(
        "Choir Program Desk",
        "<h2>Celebrate community music</h2>"
        "<p>Browse concerts and preview a dedication for the program.</p>"
        '<form action="/dedications/preview" method="post">'
        '<label>Dedication: <textarea name="dedication" maxlength="300">'
        "</textarea></label>"
        '<button type="submit">Preview dedication</button>'
        "</form>",
    )


@app.get("/concerts")
async def list_concerts(request):
    items = "".join(
        "<li>"
        f"<strong>{escape(concert['title'])}</strong>"
        f" — {escape(concert['venue'])}"
        f" — {concert['minutes']} minutes"
        "</li>"
        for concert in CONCERTS.values()
    )
    return html_response(
        "Concerts",
        "<h2>Upcoming concerts</h2><ul>" + items + "</ul>",
    )


@app.post("/dedications/preview")
async def preview_dedication(request):
    dedication = request.form.get("dedication", "").strip()

    if not dedication or len(dedication) > 300:
        return html_response(
            "Invalid Dedication",
            "<h2>Dedication must contain 1–300 characters.</h2>",
            status=400,
        )

    # CWE-79: user text can terminate the textarea and inject HTML.
    body = (
        "<h2>Program dedication editor</h2>"
        '<form action="/dedications/preview" method="post">'
        f'<textarea name="dedication" maxlength="300">{dedication}</textarea>'
        '<button type="submit">Preview again</button>'
        "</form>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response("Dedication Preview", body)


@app.get("/health")
async def health(request):
    return json(
        {
            "status": "ok",
            "concert_count": len(CONCERTS),
        }
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8620,
        debug=False,
        single_process=True,
    )
