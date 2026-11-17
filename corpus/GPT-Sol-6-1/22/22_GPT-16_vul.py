import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.serving import run_simple
from werkzeug.wrappers import Request, Response


DATA_ROOT = Path(__file__).resolve().parent / "board_game_club"
RULE_ROOT = DATA_ROOT / "rule_summaries"

GAMES = {
    "orchard": {
        "title": "Orchard Traders",
        "players": "2-4",
        "duration_minutes": 45,
    },
    "lighthouse": {
        "title": "Lighthouse Keepers",
        "players": "1-5",
        "duration_minutes": 60,
    },
    "railways": {
        "title": "Pocket Railways",
        "players": "2-6",
        "duration_minutes": 30,
    },
}

SAMPLE_RULES = {
    "orchard.txt": (
        "Orchard Traders\n"
        "Collect produce and complete market contracts.\n"
        "The highest score after six rounds wins.\n"
    ),
    "lighthouse.txt": (
        "Lighthouse Keepers\n"
        "Maintain supplies and guide ships to safety.\n"
        "Players win together if the harbor remains open.\n"
    ),
    "railways.txt": (
        "Pocket Railways\n"
        "Build routes between neighboring towns.\n"
        "Score points for completed delivery tickets.\n"
    ),
}

SESSIONS = []


def initialize_storage():
    RULE_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_RULES.items():
        destination = RULE_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(payload, status=200):
    return Response(
        json.dumps(payload),
        status=status,
        content_type="application/json; charset=utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def list_games():
    return json_response(
        {
            "games": [
                {"id": game_id, **details}
                for game_id, details in GAMES.items()
            ]
        }
    )


def create_session(request):
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return json_response({"error": "Expected a JSON object."}, 400)

    game_id = payload.get("game_id")
    organizer = payload.get("organizer")

    if not isinstance(game_id, str) or game_id not in GAMES:
        return json_response({"error": "Unknown game."}, 400)

    if not isinstance(organizer, str) or not organizer.strip():
        return json_response({"error": "Organizer is required."}, 400)

    session = {
        "id": len(SESSIONS) + 1,
        "game_id": game_id,
        "organizer": organizer,
        "created_at": current_time(),
    }
    SESSIONS.append(session)
    return json_response(session, 201)


def read_rule_summary(request):
    parameters = request.headers.get("X-Rule-Document", "orchard.txt")
    filename = parameters.strip()

    if not filename:
        return json_response({"error": "Rule document is required."}, 400)

    # CWE-22: a custom HTTP header reaches a filesystem read unchecked.
    rule_path = RULE_ROOT / filename

    try:
        content = rule_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return json_response({"error": "Rule summary not found."}, 404)
    except (OSError, UnicodeError, ValueError):
        return json_response({"error": "Rule summary cannot be read."}, 400)

    return Response(
        content,
        content_type="text/plain; charset=utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@Request.application
def application(request):
    if request.path == "/" and request.method == "GET":
        return json_response(
            {
                "application": "Board Game Club Session Desk",
                "games": "/games",
                "sessions": "/sessions",
                "rules": "/rules",
            }
        )

    if request.path == "/games" and request.method == "GET":
        return list_games()

    if request.path == "/sessions":
        if request.method == "GET":
            return json_response({"sessions": SESSIONS})
        if request.method == "POST":
            return create_session(request)

    if request.path == "/rules" and request.method == "GET":
        return read_rule_summary(request)

    return json_response({"error": "Endpoint not found."}, 404)


def main():
    parser = argparse.ArgumentParser(
        description="Run the board game club session desk."
    )
    parser.add_argument("--port", type=int, default=8190)
    args = parser.parse_args()

    initialize_storage()
    run_simple(
        hostname="127.0.0.1",
        port=args.port,
        application=application,
        use_debugger=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
