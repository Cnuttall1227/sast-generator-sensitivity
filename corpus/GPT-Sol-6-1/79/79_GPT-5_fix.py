from datetime import datetime, timezone
from html import escape

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route


EXHIBITS = {
    "engines": {
        "title": "Engines Through Time",
        "room": "Machinery Hall",
        "minutes": 20,
    },
    "signals": {
        "title": "Railway Signals",
        "room": "Control Gallery",
        "minutes": 15,
    },
    "carriages": {
        "title": "Passenger Carriages",
        "room": "Platform Gallery",
        "minutes": 25,
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
        "<header><h1>Railway Museum Group Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/exhibits">Exhibits</a></nav>'
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


async def index(request: Request):
    return html_response(
        "Museum Group Desk",
        "<h2>Arrange a museum visit</h2>"
        "<p>Browse exhibits or create a group label.</p>"
        "<p>The group label endpoint accepts a JSON object containing "
        "a label field.</p>",
    )


async def list_exhibits(request: Request):
    items = "".join(
        "<li>"
        f"<strong>{escape(exhibit['title'])}</strong>"
        f" — {escape(exhibit['room'])}"
        f" — {exhibit['minutes']} minutes"
        "</li>"
        for exhibit in EXHIBITS.values()
    )
    return html_response("Exhibits", f"<h2>Exhibits</h2><ul>{items}</ul>")


async def preview_label(request: Request):
    body = bytearray()

    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 4096:
            return html_response(
                "Invalid Label",
                "<h2>Request body is too large.</h2>",
                status_code=413,
            )

    import json

    try:
        payload = json.loads(bytes(body))
    except (ValueError, UnicodeError):
        return html_response(
            "Invalid Label",
            "<h2>Expected valid JSON.</h2>",
            status_code=400,
        )

    if not isinstance(payload, dict):
        return html_response(
            "Invalid Label",
            "<h2>Expected a JSON object.</h2>",
            status_code=400,
        )

    label = payload.get("label")

    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 200:
        return html_response(
            "Invalid Label",
            "<h2>Label must contain 1–200 characters.</h2>",
            status_code=400,
        )

    content = (
        "<h2>Group label preview</h2>"
        f'<section class="group-label"><p>{escape(label)}</p></section>'
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response("Group Label", content)


async def health(request: Request):
    return JSONResponse(
        {
            "status": "ok",
            "exhibit_count": len(EXHIBITS),
        }
    )


app = Starlette(
    debug=False,
    routes=[
        Route("/", index),
        Route("/exhibits", list_exhibits),
        Route("/labels/preview", preview_label, methods=["POST"]),
        Route("/health", health),
    ],
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8560)
