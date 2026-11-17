import json
import subprocess
from datetime import datetime, timezone

from pyramid.config import Configurator
from pyramid.response import Response
from wsgiref.simple_server import make_server


EVENTS = {
    "chess": {
        "title": "Community Chess Evening",
        "room": "Activity Hall",
        "capacity": 32,
    },
    "quilting": {
        "title": "Neighborhood Quilting Circle",
        "room": "Craft Studio",
        "capacity": 18,
    },
    "language": {
        "title": "Language Exchange",
        "room": "Meeting Room",
        "capacity": 24,
    },
}

REGISTRATIONS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(payload, status=200):
    return Response(
        body=json.dumps(payload).encode("utf-8"),
        status=status,
        content_type="application/json",
        charset="utf-8",
    )


def inspect_timezone(zone):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    if not isinstance(zone, str) or not zone.strip():
        return {"ok": False, "error": "Timezone is required."}

    if len(zone) > 120:
        return {"ok": False, "error": "Timezone is too long."}

    try:
        timezone_info = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        return {"ok": False, "error": "Invalid or unavailable timezone."}

    local_time = datetime.now(timezone_info).strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )

    return {
        "ok": True,
        "timezone": zone,
        "local_time": local_time,
        "errors": "",
        "checked_at": current_time(),
    }


def index(request):
    return json_response(
        {
            "application": "Community Center Event Clock",
            "events": "/events",
            "registrations": "/registrations",
            "clock_preview": "/clock/preview",
        }
    )


def list_events(request):
    return json_response(
        {
            "events": [
                {"id": event_id, **details}
                for event_id, details in EVENTS.items()
            ]
        }
    )


def list_registrations(request):
    return json_response({"registrations": REGISTRATIONS})


def register(request):
    try:
        payload = request.json_body
    except (ValueError, UnicodeError):
        return json_response({"error": "Invalid JSON."}, status=400)

    if not isinstance(payload, dict):
        return json_response({"error": "Expected an object."}, status=400)

    event_id = payload.get("event_id")
    participant = payload.get("participant")

    if not isinstance(event_id, str) or event_id not in EVENTS:
        return json_response({"error": "Unknown event."}, status=400)

    if not isinstance(participant, str) or not participant.strip():
        return json_response({"error": "Participant is required."}, status=400)

    registration = {
        "id": len(REGISTRATIONS) + 1,
        "event_id": event_id,
        "participant": participant,
        "registered_at": current_time(),
    }
    REGISTRATIONS.append(registration)
    return json_response(registration, status=201)


def preview_clock(request):
    try:
        payload = request.json_body
    except (ValueError, UnicodeError):
        return json_response({"error": "Invalid JSON."}, status=400)

    if not isinstance(payload, dict):
        return json_response({"error": "Expected an object."}, status=400)

    return json_response(inspect_timezone(payload.get("timezone")))


def make_application():
    with Configurator() as configuration:
        configuration.add_route("index", "/")
        configuration.add_route("events", "/events")
        configuration.add_route("registrations", "/registrations")
        configuration.add_route("clock", "/clock/preview")

        configuration.add_view(index, route_name="index", request_method="GET")
        configuration.add_view(list_events, route_name="events", request_method="GET")
        configuration.add_view(
            list_registrations,
            route_name="registrations",
            request_method="GET",
        )
        configuration.add_view(
            register,
            route_name="registrations",
            request_method="POST",
        )
        configuration.add_view(
            preview_clock,
            route_name="clock",
            request_method="PATCH",
        )
        return configuration.make_wsgi_app()


def main():
    with make_server("127.0.0.1", 8330, make_application()) as server:
        print("Community event clock listening on 127.0.0.1:8330")
        server.serve_forever()


if __name__ == "__main__":
    main()
