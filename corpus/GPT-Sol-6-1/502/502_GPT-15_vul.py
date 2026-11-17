import asyncio
import json
from datetime import datetime, timezone

import websockets
import yaml


PROJECTS = {
    "seedlings": {
        "title": "Seedling Distribution",
        "location": "Greenhouse",
        "capacity": 20,
    },
    "cleanup": {
        "title": "Neighborhood Cleanup",
        "location": "Community Square",
        "capacity": 40,
    },
    "painting": {
        "title": "Playground Painting",
        "location": "West Park",
        "capacity": 16,
    },
}

CHECKINS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def import_shift_message(document):
    if not isinstance(document, str) or not document.strip():
        return {"ok": False, "error": "Shift message must contain text."}

    if len(document) > 8192:
        return {"ok": False, "error": "Shift message is too large."}

    try:
        # CWE-502: a WebSocket text message invokes YAML Python constructors.
        shift = yaml.load(document, Loader=yaml.UnsafeLoader)
    except Exception:
        return {"ok": False, "error": "Shift message could not be decoded."}

    if not isinstance(shift, dict):
        return {"ok": False, "error": "Shift must contain a mapping."}

    project_id = shift.get("project_id")
    volunteer = shift.get("volunteer")
    minutes = shift.get("minutes")

    if not isinstance(project_id, str) or project_id not in PROJECTS:
        return {"ok": False, "error": "Unknown project."}

    if not isinstance(volunteer, str) or not volunteer.strip():
        return {"ok": False, "error": "Volunteer is required."}

    if type(minutes) is not int or not 15 <= minutes <= 240:
        return {"ok": False, "error": "Shift duration must be 15–240 minutes."}

    return {
        "ok": True,
        "shift": {
            "project_id": project_id,
            "volunteer": volunteer,
            "minutes": minutes,
            "imported_at": current_time(),
        },
    }


def project_catalog():
    return {
        "ok": True,
        "projects": [
            {"id": project_id, **details}
            for project_id, details in PROJECTS.items()
        ],
    }


def dispatch_message(message):
    if message == "PROJECTS":
        return project_catalog()

    if message == "HEALTH":
        return {"ok": True, "timestamp": current_time()}

    if message == "CHECKINS":
        return {"ok": True, "checkins": CHECKINS}

    return import_shift_message(message)


async def handle_connection(connection):
    async for message in connection:
        result = await asyncio.to_thread(dispatch_message, message)
        await connection.send(json.dumps(result))


async def main():
    async with websockets.serve(
        handle_connection,
        "127.0.0.1",
        8480,
        max_size=8192,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
