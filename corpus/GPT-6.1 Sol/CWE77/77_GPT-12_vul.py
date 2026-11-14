import argparse
import json
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path


VENUES = {
    "atrium": {
        "name": "Library Atrium",
        "seats": 40,
        "equipment": "portable speakers",
    },
    "auditorium": {
        "name": "Library Auditorium",
        "seats": 150,
        "equipment": "installed sound system",
    },
    "courtyard": {
        "name": "Library Courtyard",
        "seats": 60,
        "equipment": "battery speakers",
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def list_venues():
    return {
        "venues": [
            {"id": venue_id, **details}
            for venue_id, details in VENUES.items()
        ]
    }


def load_event_plan(plan_path):
    with plan_path.open("rb") as source:
        plan = tomllib.load(source)

    event = plan.get("event")
    playback = plan.get("playback")

    if not isinstance(event, dict):
        raise ValueError("An [event] section is required.")

    if not isinstance(playback, dict):
        raise ValueError("A [playback] section is required.")

    venue_id = event.get("venue")
    title = event.get("title")

    if not isinstance(venue_id, str) or venue_id not in VENUES:
        raise ValueError("Unknown venue.")

    if not isinstance(title, str) or not title.strip():
        raise ValueError("Event title is required.")

    return {
        "venue_id": venue_id,
        "title": title,
        "player": playback.get("player"),
    }


def inspect_player_version(plan):
    player = plan.get("player")

    if not isinstance(player, str) or not player.strip():
        return {"ok": False, "error": "Playback program is required."}

    if len(player) > 200:
        return {"ok": False, "error": "Playback program name is too long."}

    # CWE-77: a TOML playback setting becomes part of a shell command.
    command = f"{player} --version"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Player inspection timed out."}
    except OSError:
        return {"ok": False, "error": "Player inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "event": plan["title"],
        "venue": VENUES[plan["venue_id"]]["name"],
        "player": player,
        "version": result.stdout[:3000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Inspect playback readiness for library events."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("venues", help="List event venues.")

    inspect_command = commands.add_parser(
        "inspect",
        help="Inspect the playback program selected in a TOML plan.",
    )
    inspect_command.add_argument("plan", type=Path)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "venues":
        print(json.dumps(list_venues(), indent=2))
        return

    try:
        plan = load_event_plan(args.plan)
    except (OSError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    result = inspect_player_version(plan)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
