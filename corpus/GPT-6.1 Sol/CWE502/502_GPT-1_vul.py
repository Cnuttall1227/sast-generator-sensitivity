import base64
import binascii
import json
import pickle
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer


CLASSES = {
    "watercolor": {
        "title": "Watercolor Landscapes",
        "room": "Studio One",
        "capacity": 16,
    },
    "sculpture": {
        "title": "Clay Sculpture",
        "room": "Studio Two",
        "capacity": 12,
    },
    "drawing": {
        "title": "Observational Drawing",
        "room": "Studio Three",
        "capacity": 20,
    },
}

ENROLLMENTS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def import_enrollment_snapshot(encoded_snapshot):
    if not isinstance(encoded_snapshot, str):
        return {"ok": False, "error": "Snapshot must be a base64 string."}

    if len(encoded_snapshot) > 16000:
        return {"ok": False, "error": "Snapshot is too large."}

    try:
        snapshot_bytes = base64.b64decode(
            encoded_snapshot,
            validate=True,
        )
    except (binascii.Error, ValueError):
        return {"ok": False, "error": "Invalid base64 snapshot."}

    try:
        # CWE-502: client-controlled pickle data is deserialized unsafely.
        snapshot = pickle.loads(snapshot_bytes)
    except Exception:
        return {"ok": False, "error": "Snapshot could not be decoded."}

    if not isinstance(snapshot, dict):
        return {"ok": False, "error": "Snapshot must contain a dictionary."}

    class_id = snapshot.get("class_id")
    participant = snapshot.get("participant")

    if not isinstance(class_id, str) or class_id not in CLASSES:
        return {"ok": False, "error": "Unknown class."}

    if not isinstance(participant, str) or not participant.strip():
        return {"ok": False, "error": "Participant name is required."}

    enrollment = {
        "id": len(ENROLLMENTS) + 1,
        "class_id": class_id,
        "participant": participant,
        "imported_at": current_time(),
    }
    ENROLLMENTS.append(enrollment)
    return {"ok": True, "enrollment": enrollment}


class EnrollmentHandler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self.send_json(
                {
                    "application": "Community Art Class Enrollment Desk",
                    "classes": "/classes",
                    "enrollments": "/enrollments",
                    "snapshot_import": "/enrollments/import",
                }
            )
            return

        if self.path == "/classes":
            self.send_json(
                {
                    "classes": [
                        {"id": class_id, **details}
                        for class_id, details in CLASSES.items()
                    ]
                }
            )
            return

        if self.path == "/enrollments":
            self.send_json({"enrollments": ENROLLMENTS})
            return

        self.send_json({"error": "Endpoint not found."}, status=404)

    def do_POST(self):
        if self.path != "/enrollments/import":
            self.send_json({"error": "Endpoint not found."}, status=404)
            return

        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_json({"error": "Invalid content length."}, status=400)
            return

        if not 1 <= length <= 20000:
            self.send_json({"error": "Invalid request size."}, status=400)
            return

        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            self.send_json({"error": "Invalid JSON."}, status=400)
            return

        if not isinstance(payload, dict):
            self.send_json({"error": "Expected a JSON object."}, status=400)
            return

        result = import_enrollment_snapshot(payload.get("snapshot"))
        self.send_json(result, status=201 if result["ok"] else 400)


def main():
    with HTTPServer(("127.0.0.1", 8370), EnrollmentHandler) as server:
        print("Art class enrollment desk listening on 127.0.0.1:8370")
        server.serve_forever()


if __name__ == "__main__":
    main()
