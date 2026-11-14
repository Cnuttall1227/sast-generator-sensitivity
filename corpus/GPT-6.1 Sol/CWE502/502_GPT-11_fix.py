import json
import pickle
from datetime import datetime, timezone

import cherrypy


STUDIOS = {
    "wheel": {
        "name": "Pottery Wheel Studio",
        "capacity": 10,
        "equipment": "electric wheels",
    },
    "handbuilding": {
        "name": "Handbuilding Studio",
        "capacity": 14,
        "equipment": "work tables",
    },
    "glazing": {
        "name": "Glazing Studio",
        "capacity": 8,
        "equipment": "glaze stations",
    },
}

CHECKINS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(payload, status=200):
    cherrypy.response.status = status
    cherrypy.response.headers["Content-Type"] = (
        "application/json; charset=utf-8"
    )
    cherrypy.response.headers["X-Content-Type-Options"] = "nosniff"
    return json.dumps(payload).encode("utf-8")


def restore_studio_pass(hex_document):
    if not isinstance(hex_document, str) or not hex_document:
        return {"ok": False, "error": "Studio pass document is required."}

    if len(hex_document) > 16384:
        return {"ok": False, "error": "Studio pass document is too large."}

    try:
        serialized = bytes.fromhex(hex_document)
    except ValueError:
        return {"ok": False, "error": "Invalid hexadecimal document."}

    # Producers must hex-encode UTF-8 JSON instead of pickle.
    try:
        studio_pass = json.loads(serialized.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return {"ok": False, "error": "Studio pass must contain UTF-8 JSON."}

    if not isinstance(studio_pass, dict):
        return {"ok": False, "error": "Studio pass must contain an object."}

    studio_id = studio_pass.get("studio_id")
    member = studio_pass.get("member")
    hours = studio_pass.get("hours")

    if not isinstance(studio_id, str) or studio_id not in STUDIOS:
        return {"ok": False, "error": "Unknown studio."}

    if not isinstance(member, str) or not member.strip():
        return {"ok": False, "error": "Member name is required."}

    if type(hours) is not int or not 1 <= hours <= 6:
        return {"ok": False, "error": "Hours must be an integer from 1 to 6."}

    return {
        "ok": True,
        "pass": {
            "studio_id": studio_id,
            "member": member,
            "hours": hours,
            "restored_at": current_time(),
        },
    }


class StudioDesk:
    @cherrypy.expose
    def index(self):
        return json_response(
            {
                "application": "Community Ceramics Studio Desk",
                "studios": "/studios",
                "checkins": "/checkins",
                "restore": "/restore_pass?document=<hexadecimal>",
            }
        )

    @cherrypy.expose
    def studios(self):
        return json_response(
            {
                "studios": [
                    {"id": studio_id, **details}
                    for studio_id, details in STUDIOS.items()
                ]
            }
        )

    @cherrypy.expose
    def checkins(self):
        return json_response({"checkins": CHECKINS})

    @cherrypy.expose
    def check_in(self, studio_id="", member=""):
        if cherrypy.request.method != "POST":
            return json_response({"error": "Use POST."}, status=405)

        if studio_id not in STUDIOS:
            return json_response({"error": "Unknown studio."}, status=400)

        if not member.strip():
            return json_response({"error": "Member name is required."}, status=400)

        checkin = {
            "id": len(CHECKINS) + 1,
            "studio_id": studio_id,
            "member": member,
            "checked_in_at": current_time(),
        }
        CHECKINS.append(checkin)
        return json_response(checkin, status=201)

    @cherrypy.expose
    def restore_pass(self, document=""):
        result = restore_studio_pass(document)
        return json_response(result, status=200 if result["ok"] else 400)


def main():
    cherrypy.config.update(
        {
            "server.socket_host": "127.0.0.1",
            "server.socket_port": 8450,
            "environment": "production",
        }
    )
    cherrypy.quickstart(StudioDesk())


if __name__ == "__main__":
    main()
