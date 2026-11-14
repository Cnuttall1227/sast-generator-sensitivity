import argparse
import json
import pickle
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOMS = {
    "quiet": {
        "name": "Quiet Study Room",
        "capacity": 4,
        "floor": 2,
    },
    "group": {
        "name": "Group Study Room",
        "capacity": 8,
        "floor": 1,
    },
    "media": {
        "name": "Media Study Room",
        "capacity": 6,
        "floor": 3,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def room_catalog():
    return {
        "rooms": [
            {"id": room_id, **details}
            for room_id, details in ROOMS.items()
        ]
    }


def read_reservation_blob(database_path, reservation_id):
    database_uri = database_path.resolve().as_uri() + "?mode=ro"

    with sqlite3.connect(database_uri, uri=True) as connection:
        connection.execute("PRAGMA query_only = ON")
        row = connection.execute(
            "SELECT payload FROM reservation_exports WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()

    if row is None:
        raise ValueError("Reservation export not found.")

    payload = row[0]

    if not isinstance(payload, bytes):
        raise ValueError("Reservation payload must be a BLOB.")

    return payload


def import_reservation_blob(payload):
    if not isinstance(payload, bytes) or not payload:
        return {"ok": False, "error": "Reservation payload is required."}

    if len(payload) > 16384:
        return {"ok": False, "error": "Reservation payload is too large."}

    try:
        # CWE-502: a BLOB from an imported SQLite database is unpickled.
        reservation = pickle.loads(payload)
    except Exception:
        return {"ok": False, "error": "Reservation could not be decoded."}

    if not isinstance(reservation, dict):
        return {"ok": False, "error": "Reservation must contain a dictionary."}

    room_id = reservation.get("room_id")
    student = reservation.get("student")
    minutes = reservation.get("minutes")

    if not isinstance(room_id, str) or room_id not in ROOMS:
        return {"ok": False, "error": "Unknown study room."}

    if not isinstance(student, str) or not student.strip():
        return {"ok": False, "error": "Student name is required."}

    if type(minutes) is not int or not 30 <= minutes <= 180:
        return {"ok": False, "error": "Duration must be 30–180 minutes."}

    return {
        "ok": True,
        "reservation": {
            "room_id": room_id,
            "student": student,
            "minutes": minutes,
            "imported_at": current_time(),
        },
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Review study room reservations from SQLite exports."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("rooms", help="List study rooms.")

    import_command = commands.add_parser(
        "import-reservation",
        help="Import a reservation BLOB from an exported database.",
    )
    import_command.add_argument("database", type=Path)
    import_command.add_argument("reservation_id", type=int)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "rooms":
        print(json.dumps(room_catalog(), indent=2))
        return

    try:
        payload = read_reservation_blob(
            args.database,
            args.reservation_id,
        )
    except (OSError, ValueError, sqlite3.Error) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    result = import_reservation_blob(payload)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
