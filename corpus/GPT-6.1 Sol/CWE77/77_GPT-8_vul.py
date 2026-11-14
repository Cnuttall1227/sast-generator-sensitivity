import json
import subprocess
from datetime import datetime, timezone

import tornado.ioloop
import tornado.web


RECORDINGS = {
    "birds": {
        "title": "Morning Bird Survey",
        "location": "North Marsh",
        "duration_minutes": 20,
    },
    "frogs": {
        "title": "Evening Frog Survey",
        "location": "Willow Pond",
        "duration_minutes": 15,
    },
    "insects": {
        "title": "Summer Insect Survey",
        "location": "Meadow Trail",
        "duration_minutes": 30,
    },
}

ANNOTATIONS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def inspect_audio_device(device_name):
    if not isinstance(device_name, str) or not device_name.strip():
        return {"ok": False, "error": "Audio device is required."}

    if len(device_name) > 200:
        return {"ok": False, "error": "Audio device name is too long."}

    # CWE-77: a cookie value is interpolated into a shell command.
    command = f"amixer -D {device_name} sget Master"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Audio device inspection timed out."}
    except OSError:
        return {"ok": False, "error": "Audio device inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "device": device_name,
        "output": result.stdout[:3000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
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
                "application": "Wildlife Recording Review Desk",
                "recordings": "/recordings",
                "annotations": "/annotations",
                "audio_check": "/review/audio-check",
                "device_selector": "review_audio_device cookie",
            }
        )


class RecordingsHandler(BaseHandler):
    def get(self):
        self.write_json(
            {
                "recordings": [
                    {"id": recording_id, **details}
                    for recording_id, details in RECORDINGS.items()
                ]
            }
        )


class AnnotationsHandler(BaseHandler):
    def get(self):
        self.write_json({"annotations": ANNOTATIONS})

    def post(self):
        recording_id = self.get_body_argument("recording_id", "")
        note = self.get_body_argument("note", "")

        if recording_id not in RECORDINGS:
            self.write_json({"error": "Unknown recording."}, status=400)
            return

        if not note.strip() or len(note) > 1000:
            self.write_json({"error": "Invalid annotation."}, status=400)
            return

        annotation = {
            "id": len(ANNOTATIONS) + 1,
            "recording_id": recording_id,
            "note": note,
            "created_at": current_time(),
        }
        ANNOTATIONS.append(annotation)
        self.write_json(annotation, status=201)


class AudioCheckHandler(BaseHandler):
    def get(self):
        device_name = self.get_cookie(
            "review_audio_device",
            default="default",
        )
        self.write_json(inspect_audio_device(device_name))


class HealthHandler(BaseHandler):
    def get(self):
        self.write_json(
            {
                "status": "ok",
                "timestamp": current_time(),
                "recording_count": len(RECORDINGS),
            }
        )


def make_application():
    return tornado.web.Application(
        [
            (r"/", IndexHandler),
            (r"/recordings", RecordingsHandler),
            (r"/annotations", AnnotationsHandler),
            (r"/review/audio-check", AudioCheckHandler),
            (r"/health", HealthHandler),
        ],
        debug=False,
    )


def main():
    application = make_application()
    application.listen(8270, address="127.0.0.1")
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
