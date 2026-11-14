import argparse
import json
import subprocess
from datetime import datetime, timezone

from werkzeug.serving import run_simple
from werkzeug.wrappers import Request, Response


TEAMS = {
    "robotics": {
        "name": "Robotics Club",
        "room": "Engineering Lab",
        "members": 18,
    },
    "astronomy": {
        "name": "Astronomy Club",
        "room": "Science Center",
        "members": 24,
    },
    "photography": {
        "name": "Photography Club",
        "room": "Media Studio",
        "members": 16,
    },
}

CHECKOUTS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(payload, status=200):
    return Response(
        json.dumps(payload),
        status=status,
        content_type="application/json; charset=utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def inspect_usb_device(device_id):
    if not isinstance(device_id, str) or not device_id.strip():
        return {"ok": False, "error": "USB device identifier is required."}

    if len(device_id) > 120:
        return {"ok": False, "error": "USB device identifier is too long."}

    # CWE-77: an HTTP Referer query parameter enters a shell command.
    command = f"lsusb -d {device_id}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "USB inspection timed out."}
    except OSError:
        return {"ok": False, "error": "USB inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "device_id": device_id,
        "details": result.stdout[:3000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


def create_checkout(request):
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return json_response({"error": "Expected a JSON object."}, 400)

    team_id = payload.get("team_id")
    item = payload.get("item")

    if not isinstance(team_id, str) or team_id not in TEAMS:
        return json_response({"error": "Unknown team."}, 400)

    if not isinstance(item, str) or not item.strip():
        return json_response({"error": "Item description is required."}, 400)

    checkout = {
        "id": len(CHECKOUTS) + 1,
        "team_id": team_id,
        "item": item,
        "created_at": current_time(),
    }
    CHECKOUTS.append(checkout)
    return json_response(checkout, 201)


@Request.application
def application(request):
    if request.path == "/" and request.method == "GET":
        return json_response(
            {
                "application": "Student Club Equipment Desk",
                "teams": "/teams",
                "checkouts": "/checkouts",
                "usb_check": "/equipment/usb-check",
                "selector": "device parameter in the Referer URL",
            }
        )

    if request.path == "/teams" and request.method == "GET":
        return json_response(
            {
                "teams": [
                    {"id": team_id, **details}
                    for team_id, details in TEAMS.items()
                ]
            }
        )

    if request.path == "/checkouts":
        if request.method == "GET":
            return json_response({"checkouts": CHECKOUTS})
        if request.method == "POST":
            return create_checkout(request)

    if request.path == "/equipment/usb-check" and request.method == "GET":
        from urllib.parse import parse_qs, urlsplit

        referer = request.headers.get("Referer", "")
        try:
            parameters = parse_qs(urlsplit(referer).query)
        except ValueError:
            return json_response({"error": "Invalid Referer URL."}, 400)

        device_id = parameters.get("device", ["0000:0000"])[0]
        return json_response(inspect_usb_device(device_id))

    return json_response({"error": "Endpoint not found."}, 404)


def main():
    parser = argparse.ArgumentParser(
        description="Run the student club equipment desk."
    )
    parser.add_argument("--port", type=int, default=8320)
    args = parser.parse_args()

    run_simple(
        hostname="127.0.0.1",
        port=args.port,
        application=application,
        use_debugger=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
