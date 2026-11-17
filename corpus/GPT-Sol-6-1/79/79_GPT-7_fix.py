from datetime import datetime, timezone
from html import escape

from aiohttp import web


routes = web.RouteTableDef()

ACTIVITIES = {
    "pond": {
        "title": "Pond Life Survey",
        "location": "East Pond",
        "minutes": 45,
    },
    "trees": {
        "title": "Tree Identification",
        "location": "Woodland Trail",
        "minutes": 60,
    },
    "insects": {
        "title": "Insect Observation",
        "location": "Wildflower Meadow",
        "minutes": 30,
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
        "<header><h1>Nature Club Activity Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/activities">Activities</a></nav>'
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
        "Nature Club",
        "<h2>Explore the outdoors</h2>"
        "<p>Browse activities and preview a field notebook cover.</p>"
        '<form action="/notebooks/preview" method="post" '
        'enctype="multipart/form-data">'
        '<label>Notebook title: <input name="title" maxlength="150"></label>'
        '<button type="submit">Preview cover</button>'
        "</form>",
    )


@routes.get("/activities")
async def list_activities(request):
    items = "".join(
        "<li>"
        f"<strong>{escape(activity['title'])}</strong>"
        f" — {escape(activity['location'])}"
        f" — {activity['minutes']} minutes"
        "</li>"
        for activity in ACTIVITIES.values()
    )
    return html_response(
        "Activities",
        "<h2>Available activities</h2><ul>" + items + "</ul>",
    )


@routes.post("/notebooks/preview")
async def preview_notebook(request):
    if request.content_type != "multipart/form-data":
        return html_response(
            "Invalid Notebook",
            "<h2>Expected multipart form data.</h2>",
            status=400,
        )

    reader = await request.multipart()
    part = await reader.next()

    if part is None or part.name != "title" or part.filename:
        return html_response(
            "Invalid Notebook",
            "<h2>A title text field is required.</h2>",
            status=400,
        )

    data = bytearray()

    while True:
        chunk = await part.read_chunk()
        if not chunk:
            break
        data.extend(chunk)

        if len(data) > 600:
            return html_response(
                "Invalid Notebook",
                "<h2>Notebook title is too large.</h2>",
                status=400,
            )

    try:
        title = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return html_response(
            "Invalid Notebook",
            "<h2>Notebook title must be UTF-8.</h2>",
            status=400,
        )

    if not title or len(title) > 150:
        return html_response(
            "Invalid Notebook",
            "<h2>Notebook title must contain 1–150 characters.</h2>",
            status=400,
        )

    body = (
        "<h2>Field notebook cover</h2>"
        '<section class="notebook">'
        f"<h3>{escape(title)}</h3>"
        "<p>Nature Club Field Notes</p>"
        "</section>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response("Notebook Preview", body)


@routes.get("/health")
async def health(request):
    return web.json_response(
        {
            "status": "ok",
            "activity_count": len(ACTIVITIES),
        }
    )


def make_application():
    application = web.Application(client_max_size=4096)
    application.add_routes(routes)
    return application


if __name__ == "__main__":
    web.run_app(make_application(), host="127.0.0.1", port=8580)
