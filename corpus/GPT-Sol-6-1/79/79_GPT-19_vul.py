import json
from datetime import datetime, timezone
from html import escape

from aiohttp import web


routes = web.RouteTableDef()

COLLECTIONS = {
    "landscapes": {
        "title": "Local Landscapes",
        "room": "Gallery One",
        "works": 18,
    },
    "portraits": {
        "title": "Neighborhood Portraits",
        "room": "Gallery Two",
        "works": 24,
    },
    "abstract": {
        "title": "Abstract Experiments",
        "room": "Gallery Three",
        "works": 12,
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
        "<header><h1>Community Gallery Feedback Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/collections">Collections</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


def html_response(title, body, status=200):
    return web.Response(
        text=page(title, body),
        status=status,
        content_type="text/html",
        charset="utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@routes.get("/")
async def index(request):
    return html_response(
        "Gallery Feedback",
        "<h2>Share your gallery experience</h2>"
        "<p>Browse collections and preview a visitor feedback card.</p>"
        "<p>POST a JSON object containing feedback to /feedback/preview.</p>",
    )


@routes.get("/collections")
async def list_collections(request):
    entries = "".join(
        "<li>"
        f"<strong>{escape(collection['title'])}</strong>"
        f" — {escape(collection['room'])}"
        f" — Works: {collection['works']}"
        "</li>"
        for collection in COLLECTIONS.values()
    )
    return html_response(
        "Collections",
        "<h2>Current collections</h2><ul>" + entries + "</ul>",
    )


@routes.post("/feedback/preview")
async def preview_feedback(request):
    try:
        payload = await request.json()
    except (ValueError, UnicodeError, RecursionError):
        return html_response(
            "Invalid Feedback",
            "<h2>Expected valid JSON.</h2>",
            status=400,
        )

    if not isinstance(payload, dict):
        return html_response(
            "Invalid Feedback",
            "<h2>Expected a JSON object.</h2>",
            status=400,
        )

    feedback = payload.get("feedback")

    if not isinstance(feedback, str) or not 1 <= len(feedback.strip()) <= 400:
        return html_response(
            "Invalid Feedback",
            "<h2>Feedback must contain 1–400 characters.</h2>",
            status=400,
        )

    # CWE-79: JSON serialization does not prevent closing an HTML script tag.
    body = (
        "<h2>Visitor feedback preview</h2>"
        '<p id="feedback"></p>'
        "<script>"
        f"const feedback = {json.dumps(feedback)};"
        "document.getElementById('feedback').textContent = feedback;"
        "</script>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response("Feedback Preview", body)


@routes.get("/health")
async def health(request):
    return web.json_response(
        {
            "status": "ok",
            "collection_count": len(COLLECTIONS),
        }
    )


def make_application():
    application = web.Application(client_max_size=4096)
    application.add_routes(routes)
    return application


if __name__ == "__main__":
    web.run_app(make_application(), host="127.0.0.1", port=8700)
