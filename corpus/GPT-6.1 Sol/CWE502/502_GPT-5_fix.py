import base64
import binascii
import json
import pickle
from datetime import datetime, timezone

import tornado.ioloop
import tornado.web


SESSIONS = {
    "morning": {
        "title": "Morning Rowing Practice",
        "launch": "North Dock",
        "capacity": 8,
    },
    "afternoon": {
        "title": "Afternoon Paddling",
        "launch": "East Dock",
        "capacity": 12,
    },
    "evening": {
        "title": "Evening Safety Training",
        "launch": "Clubhouse",
        "capacity": 16,
    },
}

CHECKINS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def restore_roster_cookie(encoded_roster):
    if not isinstance(encoded_roster, str) or not encoded_roster:
        return {"ok": False, "error": "Roster cookie is required."}

    if len(encoded_roster) > 4096:
        return {"ok": False, "error": "Roster cookie is too large."}

    try:
        data = base64.b64decode(encoded_roster, validate=True)
    except (binascii.Error, ValueError):
        return {"ok": False, "error": "Invalid roster encoding."}

    # Cookie producers must encode UTF-8 JSON instead of pickle.
    try:
        roster = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return {"ok": False, "error": "Roster must contain valid UTF-8 JSON."}

    if not isinstance(roster, dict):
        return {"ok": False, "error": "Roster must contain an object."}

    session_id = roster.get("session_id")
    captain = roster.get("captain")
    crew_size = roster.get("crew_size")

    if not isinstance(session_id, str) or session_id not in SESSIONS:
        return {"ok": False, "error": "Unknown session."}

    if not isinstance(captain, str) or not captain.strip():
        return {"ok": False, "error": "Captain name is required."}

    if type(crew_size) is not int:
        return {"ok": False, "error": "Crew size must be an integer."}

    if not 1 <= crew_size <= SESSIONS[session_id]["capacity"]:
        return {"ok": False, "error": "Crew size exceeds session capacity."}

    return {
        "ok": True,
        "roster": {
            "session_id": session_id,
            "captain": captain,
            "crew_size": crew_size,
            "restored_at": current_time(),
        },
    }


class BaseHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("X-Content-Type-Options", "nosniff")

    def write_json(self, payload, status=200):
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.finish(json.dumps(payload))


class IndexHandler(BaseHandler):
    def get(self):
        self.write_json(
            {
                "application": "Community Boating Roster Desk",
                "sessions": "/sessions",
                "checkins": "/checkins",
                "restore": "/roster/restore",
                "selector": "boating_roster browser cookie",
            }
        )


class SessionsHandler(BaseHandler):
    def get(self):
        self.write_json(
            {
                "sessions": [
                    {"id": session_id, **details}
                    for session_id, details in SESSIONS.items()
                ]
            }
        )


class CheckinsHandler(BaseHandler):
    def get(self):
        self.write_json({"checkins": CHECKINS})

    def post(self):
        session_id = self.get_body_argument("session_id", "")
        visitor = self.get_body_argument("visitor", "")

        if session_id not in SESSIONS:
            self.write_json({"error": "Unknown session."}, status=400)
            return

        if not visitor.strip():
            self.write_json({"error": "Visitor name is required."}, status=400)
            return

        checkin = {
            "id": len(CHECKINS) + 1,
            "session_id": session_id,
            "visitor": visitor,
            "checked_in_at": current_time(),
        }
        CHECKINS.append(checkin)
        self.write_json(checkin, status=201)


class RestoreRosterHandler(BaseHandler):
    def get(self):
        encoded_roster = self.get_cookie("boating_roster", default="")
        result = restore_roster_cookie(encoded_roster)
        self.write_json(result, status=200 if result["ok"] else 400)


def main():
    application = tornado.web.Application(
        [
            (r"/", IndexHandler),
            (r"/sessions", SessionsHandler),
            (r"/checkins", CheckinsHandler),
            (r"/roster/restore", RestoreRosterHandler),
        ],
        debug=False,
    )
    application.listen(8400, address="127.0.0.1")
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
