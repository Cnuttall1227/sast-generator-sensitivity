import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import make_server


ROOT = Path(__file__).resolve().parent / "radio_station"
PLAYLIST_ROOT = ROOT / "playlists"

PROGRAMS = {
    "morning": {
        "title": "Morning Signals",
        "host": "Avery",
        "genre": "Jazz",
        "start": "07:00",
    },
    "afternoon": {
        "title": "Afternoon Frequencies",
        "host": "Morgan",
        "genre": "Indie",
        "start": "13:00",
    },
    "evening": {
        "title": "Evening Echoes",
        "host": "Taylor",
        "genre": "Ambient",
        "start": "20:00",
    },
}

SAMPLE_PLAYLISTS = {
    "morning.txt": [
        "Northern Quartet - First Light",
        "Mira Lane - Open Windows",
        "Blue Platform - Passing Trains",
    ],
    "afternoon.txt": [
        "Paper Satellites - Side Streets",
        "June Harbor - Static Bloom",
        "Glass Orchard - Turning Pages",
    ],
    "evening.txt": [
        "Slow Horizon - Still Water",
        "Cloud Archive - Distant Rooms",
        "Lunar Field - Quiet Motion",
    ],
}


def initialize_storage():
    PLAYLIST_ROOT.mkdir(parents=True, exist_ok=True)
    for filename, tracks in SAMPLE_PLAYLISTS.items():
        destination = PLAYLIST_ROOT / filename
        if not destination.exists():
            destination.write_text(
                "\n".join(tracks) + "\n",
                encoding="utf-8",
            )


def respond(start_response, status, body, content_type):
    encoded = body.encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", content_type),
            ("Content-Length", str(len(encoded))),
            ("X-Content-Type-Options", "nosniff"),
        ],
    )
    return [encoded]


def json_response(start_response, status, payload):
    return respond(
        start_response,
        status,
        json.dumps(payload, indent=2),
        "application/json; charset=utf-8",
    )


def program_list():
    return [
        {"id": program_id, **details}
        for program_id, details in PROGRAMS.items()
    ]


def export_playlist(environ, start_response):
    # CWE-22: a request header controls a path without containment checks.
    filename = environ.get("HTTP_X_PLAYLIST_FILE", "morning.txt")
    playlist_path = PLAYLIST_ROOT / filename

    try:
        content = playlist_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return json_response(
            start_response,
            "404 Not Found",
            {"error": "Playlist file not found."},
        )
    except (PermissionError, UnicodeError, ValueError, OSError):
        return json_response(
            start_response,
            "400 Bad Request",
            {"error": "Playlist file cannot be exported."},
        )

    return respond(
        start_response,
        "200 OK",
        content,
        "text/plain; charset=utf-8",
    )


def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/")

    if method != "GET":
        return json_response(
            start_response,
            "405 Method Not Allowed",
            {"error": "Only GET requests are supported."},
        )

    if path == "/":
        return json_response(
            start_response,
            "200 OK",
            {
                "application": "Community Radio Schedule",
                "programs": "/programs",
                "export": "/playlists/export",
                "export_header": "X-Playlist-File",
            },
        )

    if path == "/health":
        return json_response(
            start_response,
            "200 OK",
            {
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    if path == "/programs":
        return json_response(
            start_response,
            "200 OK",
            {"programs": program_list()},
        )

    if path == "/playlists/export":
        return export_playlist(environ, start_response)

    return json_response(
        start_response,
        "404 Not Found",
        {"error": "Endpoint not found."},
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run the community radio schedule application."
    )
    parser.add_argument("--port", type=int, default=8070)
    args = parser.parse_args()

    initialize_storage()

    with make_server("127.0.0.1", args.port, application) as server:
        print(f"Radio schedule available at http://127.0.0.1:{args.port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
