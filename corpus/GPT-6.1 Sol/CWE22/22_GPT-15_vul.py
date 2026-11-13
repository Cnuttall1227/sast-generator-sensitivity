import json
from datetime import datetime, timezone
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route


DATA_ROOT = Path(__file__).resolve().parent / "community_orchestra"
SCORE_ROOT = DATA_ROOT / "rehearsal_notes"

SECTIONS = {
    "strings": {
        "name": "String Section",
        "room": "Studio A",
        "players": 18,
    },
    "woodwinds": {
        "name": "Woodwind Section",
        "room": "Studio B",
        "players": 8,
    },
    "brass": {
        "name": "Brass Section",
        "room": "Main Hall",
        "players": 10,
    },
}

SAMPLE_NOTES = {
    "strings.txt": (
        "String rehearsal notes\n"
        "Review bowing in the opening movement.\n"
        "Practice the final passage at reduced tempo.\n"
    ),
    "woodwinds.txt": (
        "Woodwind rehearsal notes\n"
        "Check articulation in the second movement.\n"
        "Coordinate breathing before the reprise.\n"
    ),
    "brass.txt": (
        "Brass rehearsal notes\n"
        "Balance dynamics against the string section.\n"
        "Review entrances following the percussion solo.\n"
    ),
}

ATTENDANCE = []


def initialize_storage():
    SCORE_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_NOTES.items():
        destination = SCORE_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


async def index(request: Request):
    return JSONResponse(
        {
            "application": "Community Orchestra Rehearsal Desk",
            "sections": "/sections",
            "attendance": "/attendance",
            "notes": "/notes",
            "selector": "JSON in the X-Rehearsal-Selection header",
        }
    )


async def list_sections(request: Request):
    return JSONResponse(
        {
            "sections": [
                {"id": section_id, **details}
                for section_id, details in SECTIONS.items()
            ]
        }
    )


async def list_attendance(request: Request):
    return JSONResponse({"attendance": ATTENDANCE})


async def record_attendance(request: Request):
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse(
            {"error": "Expected a JSON object."},
            status_code=400,
        )

    section_id = payload.get("section_id")
    musician = payload.get("musician")

    if not isinstance(section_id, str) or section_id not in SECTIONS:
        return JSONResponse({"error": "Unknown section."}, status_code=400)

    if not isinstance(musician, str) or not musician.strip():
        return JSONResponse(
            {"error": "Musician name is required."},
            status_code=400,
        )

    record = {
        "id": len(ATTENDANCE) + 1,
        "section_id": section_id,
        "musician": musician,
        "recorded_at": current_time(),
    }
    ATTENDANCE.append(record)
    return JSONResponse(record, status_code=201)


async def read_notes(request: Request):
    raw_selection = request.headers.get(
        "X-Rehearsal-Selection",
        '{"document": "strings.txt"}',
    )

    try:
        selection = json.loads(raw_selection)
    except (ValueError, UnicodeError):
        return JSONResponse(
            {"error": "Invalid selection JSON."},
            status_code=400,
        )

    if not isinstance(selection, dict):
        return JSONResponse(
            {"error": "Selection must be an object."},
            status_code=400,
        )

    filename = selection.get("document", "strings.txt")

    if not isinstance(filename, str) or not filename.strip():
        return JSONResponse(
            {"error": "Document must be a nonempty string."},
            status_code=400,
        )

    # CWE-22: a JSON-valued header supplies an unchecked document path.
    notes_path = SCORE_ROOT / filename

    try:
        content = notes_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return JSONResponse(
            {"error": "Rehearsal notes not found."},
            status_code=404,
        )
    except (OSError, UnicodeError, ValueError):
        return JSONResponse(
            {"error": "Rehearsal notes cannot be read."},
            status_code=400,
        )

    return PlainTextResponse(
        content,
        headers={"X-Content-Type-Options": "nosniff"},
    )


def make_application():
    initialize_storage()
    return Starlette(
        debug=False,
        routes=[
            Route("/", index),
            Route("/sections", list_sections),
            Route("/attendance", list_attendance, methods=["GET"]),
            Route("/attendance", record_attendance, methods=["POST"]),
            Route("/notes", read_notes),
        ],
    )


app = make_application()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8180)
