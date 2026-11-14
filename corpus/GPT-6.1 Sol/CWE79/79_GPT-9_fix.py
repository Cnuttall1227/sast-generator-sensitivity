import json
from datetime import datetime, timezone
from html import escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse


app = FastAPI(title="Community Film Discussion Board")

FILMS = {
    "harbor": {
        "title": "Harbor Lights",
        "director": "Mira West",
        "minutes": 92,
    },
    "summer": {
        "title": "A Long Summer",
        "director": "Rowan Lane",
        "minutes": 105,
    },
    "letters": {
        "title": "Unsent Letters",
        "director": "Alex North",
        "minutes": 88,
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
        "<header><h1>Community Film Discussion Board</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/films">Films</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


def html_response(title, body, status_code=200):
    return HTMLResponse(
        page(title, body),
        status_code=status_code,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/")
def index():
    return html_response(
        "Film Discussion",
        "<h2>Discuss this month's films</h2>"
        "<p>Browse films and preview a discussion note.</p>"
        "<p>Send a JSON PATCH array to /notes/preview to set the note text.</p>",
    )


@app.get("/films")
def list_films():
    items = "".join(
        "<li>"
        f"<strong>{escape(film['title'])}</strong>"
        f" — Directed by {escape(film['director'])}"
        f" — {film['minutes']} minutes"
        "</li>"
        for film in FILMS.values()
    )
    return html_response("Films", "<h2>Films</h2><ul>" + items + "</ul>")


@app.patch("/notes/preview")
async def preview_note(request: Request):
    body = bytearray()

    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 4096:
            return html_response(
                "Invalid Note",
                "<h2>Request body is too large.</h2>",
                status_code=413,
            )

    try:
        operations = json.loads(bytes(body))
    except (ValueError, UnicodeError, RecursionError):
        return html_response(
            "Invalid Note",
            "<h2>Expected valid JSON.</h2>",
            status_code=400,
        )

    if not isinstance(operations, list):
        return html_response(
            "Invalid Note",
            "<h2>Expected an array of note operations.</h2>",
            status_code=400,
        )

    note = "No discussion note provided."

    for operation in operations:
        if not isinstance(operation, dict):
            return html_response(
                "Invalid Note",
                "<h2>Each operation must be an object.</h2>",
                status_code=400,
            )

        if (
            operation.get("op") == "replace"
            and operation.get("path") == "/note"
        ):
            note = operation.get("value")

    if not isinstance(note, str) or not 1 <= len(note.strip()) <= 500:
        return html_response(
            "Invalid Note",
            "<h2>Note must contain 1–500 characters.</h2>",
            status_code=400,
        )

    content = (
        "<h2>Discussion note preview</h2>"
        f"<blockquote>{escape(note)}</blockquote>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response("Discussion Note", content)


@app.get("/health")
def health():
    return JSONResponse(
        {
            "status": "ok",
            "film_count": len(FILMS),
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8600)
