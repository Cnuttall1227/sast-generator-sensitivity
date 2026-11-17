import json
from datetime import datetime, timezone
from pathlib import Path

from sanic import Sanic
from sanic.response import json as json_response
from sanic.response import text


DATA_ROOT = Path(__file__).resolve().parent / "planetarium"
SCRIPT_ROOT = DATA_ROOT / "show_scripts"

SHOWS = {
    "moon": {
        "title": "Journey to the Moon",
        "duration_minutes": 25,
        "audience": "families",
    },
    "galaxies": {
        "title": "Beyond Our Galaxy",
        "duration_minutes": 40,
        "audience": "adults",
    },
    "stars": {
        "title": "Finding the Constellations",
        "duration_minutes": 30,
        "audience": "all ages",
    },
}

SAMPLE_SCRIPTS = {
    "moon.txt": (
        "Journey to the Moon\n"
        "Dim the dome lights and introduce the lunar phases.\n"
    ),
    "galaxies.txt": (
        "Beyond Our Galaxy\n"
        "Begin with the Milky Way panorama.\n"
    ),
    "stars.txt": (
        "Finding the Constellations\n"
        "Display the seasonal sky and identify Polaris.\n"
    ),
}

app = Sanic("PlanetariumShowDesk")


def initialize_storage():
    SCRIPT_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_SCRIPTS.items():
        destination = SCRIPT_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


@app.before_server_start
async def initialize_application(application, loop):
    initialize_storage()
    application.ctx.bookings = []


@app.get("/")
async def index(request):
    return json_response(
        {
            "application": "Planetarium Show Desk",
            "shows": "/shows",
            "bookings": "/bookings",
            "script_preview": "/scripts/preview",
            "selector": "PATCH JSON array with a /document operation",
        }
    )


@app.get("/shows")
async def list_shows(request):
    return json_response(
        {
            "shows": [
                {"id": show_id, **details}
                for show_id, details in SHOWS.items()
            ]
        }
    )


@app.get("/bookings")
async def list_bookings(request):
    return json_response({"bookings": request.app.ctx.bookings})


@app.post("/bookings")
async def create_booking(request):
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeError):
        return json_response({"error": "Invalid JSON."}, status=400)

    if not isinstance(payload, dict):
        return json_response({"error": "Expected an object."}, status=400)

    show_id = payload.get("show_id")
    group = payload.get("group")

    if not isinstance(show_id, str) or show_id not in SHOWS:
        return json_response({"error": "Unknown show."}, status=400)

    if not isinstance(group, str) or not group.strip():
        return json_response({"error": "Group name is required."}, status=400)

    bookings = request.app.ctx.bookings
    booking = {
        "id": len(bookings) + 1,
        "show_id": show_id,
        "group": group,
        "created_at": current_time(),
    }
    bookings.append(booking)
    return json_response(booking, status=201)


@app.patch("/scripts/preview")
async def preview_script(request):
    try:
        operations = json.loads(request.body)
    except (ValueError, UnicodeError):
        return json_response({"error": "Invalid JSON."}, status=400)

    if not isinstance(operations, list):
        return json_response(
            {"error": "Expected an array of selection operations."},
            status=400,
        )

    filename = "moon.txt"

    for operation in operations:
        if not isinstance(operation, dict):
            return json_response(
                {"error": "Each operation must be an object."},
                status=400,
            )

        if (
            operation.get("op") == "replace"
            and operation.get("path") == "/document"
        ):
            filename = operation.get("value")

    if not isinstance(filename, str) or not filename.strip():
        return json_response(
            {"error": "Document must be a nonempty string."},
            status=400,
        )

    try:
        script_directory = SCRIPT_ROOT.resolve(strict=True)
        requested_path = Path(filename)

        if requested_path.is_absolute():
            return json_response(
                {"error": "Invalid script path."},
                status=400,
            )

        script_path = (script_directory / requested_path).resolve(
            strict=True
        )

        if not script_path.is_relative_to(script_directory):
            return json_response(
                {"error": "Invalid script path."},
                status=400,
            )

        content = script_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return json_response({"error": "Script not found."}, status=404)
    except (OSError, UnicodeError, ValueError, RuntimeError):
        return json_response({"error": "Script cannot be read."}, status=400)

    return text(
        content,
        headers={"X-Content-Type-Options": "nosniff"},
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8200,
        debug=False,
        single_process=True,
    )
