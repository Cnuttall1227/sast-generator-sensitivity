from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request

app = Flask(__name__)

DATA_ROOT = Path(__file__).resolve().parent / "museum_data"
TRANSCRIPT_ROOT = DATA_ROOT / "transcripts"

EXHIBITS = {
    "navigation": {
        "title": "Navigation Through the Ages",
        "room": "North Gallery",
        "duration_minutes": 12,
        "languages": ["en", "es"],
    },
    "printing": {
        "title": "The Printing Revolution",
        "room": "East Gallery",
        "duration_minutes": 9,
        "languages": ["en"],
    },
    "astronomy": {
        "title": "Mapping the Night Sky",
        "room": "Observatory Hall",
        "duration_minutes": 15,
        "languages": ["en"],
    },
}

SAMPLE_TRANSCRIPTS = {
    ("navigation", "en"): (
        "Welcome to Navigation Through the Ages.\n"
        "This exhibit explores compasses, charts, and ocean voyages.\n"
    ),
    ("navigation", "es"): (
        "Bienvenidos a la historia de la navegación.\n"
        "Esta exposición presenta brújulas, mapas y viajes oceánicos.\n"
    ),
    ("printing", "en"): (
        "Welcome to The Printing Revolution.\n"
        "Explore how movable type changed the spread of information.\n"
    ),
    ("astronomy", "en"): (
        "Welcome to Mapping the Night Sky.\n"
        "Discover how astronomers recorded stars and constellations.\n"
    ),
}


def initialize_content():
    TRANSCRIPT_ROOT.mkdir(parents=True, exist_ok=True)
    for (exhibit_id, language), content in SAMPLE_TRANSCRIPTS.items():
        exhibit_directory = TRANSCRIPT_ROOT / exhibit_id
        exhibit_directory.mkdir(parents=True, exist_ok=True)
        destination = exhibit_directory / f"{language}.txt"
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def get_exhibit(exhibit_id):
    exhibit = EXHIBITS.get(exhibit_id)
    if exhibit is None:
        abort(404, description="Unknown exhibit.")
    return exhibit


@app.get("/")
def index():
    return jsonify(
        application="Museum Audio Guide",
        description="Browse exhibits and retrieve audio-guide transcripts.",
        endpoints={
            "exhibits": "/api/exhibits",
            "rooms": "/api/rooms",
            "health": "/health",
        },
    )


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
        exhibit_count=len(EXHIBITS),
    )


@app.get("/api/exhibits")
def list_exhibits():
    room_filter = request.args.get("room")
    results = []
    for exhibit_id, exhibit in EXHIBITS.items():
        if room_filter and exhibit["room"] != room_filter:
            continue
        results.append({"id": exhibit_id, **exhibit})
    return jsonify(exhibits=results, count=len(results))


@app.get("/api/exhibits/<exhibit_id>")
def exhibit_details(exhibit_id):
    exhibit = get_exhibit(exhibit_id)
    return jsonify(
        id=exhibit_id,
        **exhibit,
        transcript_endpoint=f"/api/exhibits/{exhibit_id}/transcript",
    )


@app.get("/api/rooms")
def list_rooms():
    rooms = sorted({exhibit["room"] for exhibit in EXHIBITS.values()})
    return jsonify(rooms=rooms)


@app.get("/api/exhibits/<exhibit_id>/transcript")
def read_transcript(exhibit_id):
    get_exhibit(exhibit_id)
    filename = request.args.get("file", "en.txt")

    # CWE-22: an attacker-controlled filename escapes the exhibit directory.
    # Example trigger: ?file=../../../../etc/passwd
    transcript_path = TRANSCRIPT_ROOT / exhibit_id / filename

    try:
        content = transcript_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        abort(404, description="Transcript not found.")
    except (PermissionError, UnicodeError, ValueError):
        abort(400, description="Transcript cannot be read.")

    return Response(
        content,
        content_type="text/plain; charset=utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


if __name__ == "__main__":
    initialize_content()
    app.run(host="127.0.0.1", port=5050, debug=False)
