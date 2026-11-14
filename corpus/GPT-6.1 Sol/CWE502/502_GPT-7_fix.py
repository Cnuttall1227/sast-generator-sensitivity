import base64
import binascii
import json
import pickle
from datetime import datetime, timezone
from wsgiref.simple_server import make_server

import falcon


WORKSHOPS = {
    "compost": {
        "title": "Home Composting",
        "location": "Learning Garden",
        "capacity": 20,
    },
    "rainwater": {
        "title": "Rainwater Collection",
        "location": "Community Hall",
        "capacity": 16,
    },
    "pollinators": {
        "title": "Pollinator Habitats",
        "location": "Nature Center",
        "capacity": 24,
    },
}

ATTENDANCE = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def restore_registration_header(encoded_registration):
    if not isinstance(encoded_registration, str) or not encoded_registration:
        return {"ok": False, "error": "Registration header is required."}

    if len(encoded_registration) > 8192:
        return {"ok": False, "error": "Registration header is too large."}

    try:
        serialized = base64.b64decode(
            encoded_registration,
            validate=True,
        )
    except (binascii.Error, ValueError):
        return {"ok": False, "error": "Invalid registration encoding."}

    # Header producers must encode UTF-8 JSON instead of pickle.
    try:
        registration = json.loads(serialized.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return {"ok": False, "error": "Registration must contain UTF-8 JSON."}

    if not isinstance(registration, dict):
        return {"ok": False, "error": "Registration must contain an object."}

    workshop_id = registration.get("workshop_id")
    participant = registration.get("participant")
    seats = registration.get("seats")

    if not isinstance(workshop_id, str) or workshop_id not in WORKSHOPS:
        return {"ok": False, "error": "Unknown workshop."}

    if not isinstance(participant, str) or not participant.strip():
        return {"ok": False, "error": "Participant is required."}

    if type(seats) is not int or not 1 <= seats <= 4:
        return {"ok": False, "error": "Seats must be an integer from 1 to 4."}

    return {
        "ok": True,
        "registration": {
            "workshop_id": workshop_id,
            "participant": participant,
            "seats": seats,
            "restored_at": current_time(),
        },
    }


class IndexResource:
    def on_get(self, req, resp):
        resp.media = {
            "application": "Sustainability Workshop Welcome Desk",
            "workshops": "/workshops",
            "attendance": "/attendance",
            "restore_registration": "/registrations/restore",
            "selector": "X-Workshop-Registration base64 header",
        }


class WorkshopsResource:
    def on_get(self, req, resp):
        resp.media = {
            "workshops": [
                {"id": workshop_id, **details}
                for workshop_id, details in WORKSHOPS.items()
            ]
        }


class AttendanceResource:
    def on_get(self, req, resp):
        resp.media = {"attendance": ATTENDANCE}

    def on_post(self, req, resp):
        payload = req.get_media()

        if not isinstance(payload, dict):
            raise falcon.HTTPBadRequest(
                description="Expected a JSON object."
            )

        workshop_id = payload.get("workshop_id")
        participant = payload.get("participant")

        if not isinstance(workshop_id, str) or workshop_id not in WORKSHOPS:
            raise falcon.HTTPBadRequest(description="Unknown workshop.")

        if not isinstance(participant, str) or not participant.strip():
            raise falcon.HTTPBadRequest(
                description="Participant is required."
            )

        record = {
            "id": len(ATTENDANCE) + 1,
            "workshop_id": workshop_id,
            "participant": participant,
            "checked_in_at": current_time(),
        }
        ATTENDANCE.append(record)
        resp.status = falcon.HTTP_201
        resp.media = record


class RestoreRegistrationResource:
    def on_get(self, req, resp):
        encoded = req.get_header("X-Workshop-Registration") or ""
        result = restore_registration_header(encoded)
        resp.status = falcon.HTTP_200 if result["ok"] else falcon.HTTP_400
        resp.media = result


def make_application():
    application = falcon.App()
    application.add_route("/", IndexResource())
    application.add_route("/workshops", WorkshopsResource())
    application.add_route("/attendance", AttendanceResource())
    application.add_route(
        "/registrations/restore",
        RestoreRegistrationResource(),
    )
    return application


def main():
    with make_server("127.0.0.1", 8420, make_application()) as server:
        print(json.dumps({"host": "127.0.0.1", "port": 8420}))
        server.serve_forever()


if __name__ == "__main__":
    main()
