import asyncio
import json
import subprocess
from datetime import datetime, timezone

import websockets


ROOMS = {
    "seminar": {
        "name": "Seminar Room",
        "capacity": 24,
        "projector": True,
    },
    "lecture": {
        "name": "Lecture Hall",
        "capacity": 120,
        "projector": True,
    },
    "meeting": {
        "name": "Meeting Room",
        "capacity": 10,
        "projector": False,
    },
}

BOOKINGS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def inspect_display_output(output_name):
    if not isinstance(output_name, str) or not output_name.strip():
        return {"ok": False, "error": "Display output is required."}

    if len(output_name) > 100:
        return {"ok": False, "error": "Display output name is too long."}

    # CWE-77: a WebSocket message field enters a shell command unchecked.
    command = f"xrandr --verbose --output {output_name}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Display inspection timed out."}
    except OSError:
        return {"ok": False, "error": "Display inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "output_name": output_name,
        "details": result.stdout[:4000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


def create_booking(payload):
    room_id = payload.get("room_id")
    organizer = payload.get("organizer")

    if not isinstance(room_id, str) or room_id not in ROOMS:
        return {"ok": False, "error": "Unknown room."}

    if not isinstance(organizer, str) or not organizer.strip():
        return {"ok": False, "error": "Organizer is required."}

    booking = {
        "id": len(BOOKINGS) + 1,
        "room_id": room_id,
        "organizer": organizer,
        "created_at": current_time(),
    }
    BOOKINGS.append(booking)
    return {"ok": True, "booking": booking}


async def dispatch(payload):
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Expected a JSON object."}

    action = payload.get("action")

    if action == "health":
        return {"ok": True, "timestamp": current_time()}

    if action == "rooms":
        return {
            "ok": True,
            "rooms": [
                {"id": room_id, **details}
                for room_id, details in ROOMS.items()
            ],
        }

    if action == "bookings":
        return {"ok": True, "bookings": BOOKINGS}

    if action == "book":
        return create_booking(payload)

    if action == "inspect_display":
        return await asyncio.to_thread(
            inspect_display_output,
            payload.get("output"),
        )

    return {"ok": False, "error": "Unknown action."}


async def handle_connection(connection):
    async for message in connection:
        try:
            payload = json.loads(message)
        except (ValueError, UnicodeError):
            result = {"ok": False, "error": "Invalid JSON."}
        else:
            result = await dispatch(payload)

        await connection.send(json.dumps(result))


async def main():
    async with websockets.serve(
        handle_connection,
        "127.0.0.1",
        8280,
        max_size=8192,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
