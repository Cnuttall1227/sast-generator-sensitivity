import base64
import binascii
import json
import pickle
from datetime import datetime, timezone
from urllib.parse import parse_qs

from wsgiref.simple_server import make_server


BEDS = {
    "herbs": {
        "name": "Herb Demonstration Bed",
        "area_m2": 12,
        "coordinator": "Alex",
    },
    "vegetables": {
        "name": "Vegetable Demonstration Bed",
        "area_m2": 24,
        "coordinator": "Morgan",
    },
    "flowers": {
        "name": "Pollinator Demonstration Bed",
        "area_m2": 18,
        "coordinator": "Jamie",
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def import_planting_token(token):
    if not isinstance(token, str) or not token:
        return {"ok": False, "error": "Planting token is required."}

    if len(token) > 4096:
        return {"ok": False, "error": "Planting token is too large."}

    try:
        serialized = base64.b64decode(
            token,
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError):
        return {"ok": False, "error": "Invalid planting token encoding."}

    try:
        # CWE-502: a form token is deserialized as an untrusted Python pickle.
        planting = pickle.loads(serialized)
    except Exception:
        return {"ok": False, "error": "Planting token could not be decoded."}

    if not isinstance(planting, dict):
        return {"ok": False, "error": "Planting must contain a dictionary."}

    bed_id = planting.get("bed_id")
    gardener = planting.get("gardener")
    seedlings = planting.get("seedlings")

    if not isinstance(bed_id, str) or bed_id not in BEDS:
        return {"ok": False, "error": "Unknown demonstration bed."}

    if not isinstance(gardener, str) or not gardener.strip():
        return {"ok": False, "error": "Gardener is required."}

    if type(seedlings) is not int or not 1 <= seedlings <= 200:
        return {"ok": False, "error": "Seedlings must be 1–200."}

    return {
        "ok": True,
        "planting": {
            "bed_id": bed_id,
            "gardener": gardener,
            "seedlings": seedlings,
            "imported_at": current_time(),
        },
    }


def respond(start_response, payload, status="200 OK"):
    encoded = json.dumps(payload).encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(encoded))),
            ("X-Content-Type-Options", "nosniff"),
        ],
    )
    return [encoded]


def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/")

    if method == "GET" and path == "/":
        return respond(
            start_response,
            {
                "application": "Demonstration Garden Planting Desk",
                "beds": "/beds",
                "import": "/plantings/import",
                "selector": "URL-encoded form field planting_token",
            },
        )

    if method == "GET" and path == "/beds":
        return respond(
            start_response,
            {
                "beds": [
                    {"id": bed_id, **details}
                    for bed_id, details in BEDS.items()
                ]
            },
        )

    if method == "POST" and path == "/plantings/import":
        try:
            length = int(environ.get("CONTENT_LENGTH", ""))
        except ValueError:
            return respond(
                start_response,
                {"error": "Invalid content length."},
                "400 Bad Request",
            )

        if not 1 <= length <= 8192:
            return respond(
                start_response,
                {"error": "Invalid request size."},
                "400 Bad Request",
            )

        try:
            body = environ["wsgi.input"].read(length).decode("utf-8")
            fields = parse_qs(body, max_num_fields=10)
        except (ValueError, UnicodeError):
            return respond(
                start_response,
                {"error": "Invalid form data."},
                "400 Bad Request",
            )

        token = fields.get("planting_token", [""])[0]
        result = import_planting_token(token)
        return respond(
            start_response,
            result,
            "201 Created" if result["ok"] else "400 Bad Request",
        )

    return respond(
        start_response,
        {"error": "Endpoint not found."},
        "404 Not Found",
    )


if __name__ == "__main__":
    with make_server("127.0.0.1", 8500, application) as server:
        server.serve_forever()
