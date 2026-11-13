import json
from datetime import datetime, timezone
from pathlib import Path

from twisted.internet import reactor
from twisted.web import resource, server


DATA_ROOT = Path(__file__).resolve().parent / "weather_balloon"
CHECKLIST_ROOT = DATA_ROOT / "checklists"

MISSIONS = {
    "dawn": {
        "name": "Dawn Atmospheric Survey",
        "altitude_m": 18000,
        "payload": "temperature",
    },
    "noon": {
        "name": "Midday Wind Survey",
        "altitude_m": 22000,
        "payload": "wind",
    },
    "dusk": {
        "name": "Evening Humidity Survey",
        "altitude_m": 16000,
        "payload": "humidity",
    },
}

SAMPLE_CHECKLISTS = {
    "dawn.txt": "Inspect envelope.\nCalibrate temperature sensor.\n",
    "noon.txt": "Inspect tether.\nCalibrate wind instrumentation.\n",
    "dusk.txt": "Inspect batteries.\nCalibrate humidity sensor.\n",
}

LAUNCHES = []


def initialize_storage():
    CHECKLIST_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_CHECKLISTS.items():
        destination = CHECKLIST_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(request, payload, status=200):
    request.setResponseCode(status)
    request.setHeader(b"content-type", b"application/json; charset=utf-8")
    request.setHeader(b"x-content-type-options", b"nosniff")
    return json.dumps(payload).encode("utf-8")


class IndexResource(resource.Resource):
    def render_GET(self, request):
        return json_response(
            request,
            {
                "application": "Weather Balloon Mission Desk",
                "missions": "/missions",
                "launches": "/launches",
                "checklist": "/checklist",
                "selector": "PUT body containing a UTF-8 filename",
            },
        )


class MissionsResource(resource.Resource):
    isLeaf = True

    def render_GET(self, request):
        return json_response(
            request,
            {
                "missions": [
                    {"id": mission_id, **details}
                    for mission_id, details in MISSIONS.items()
                ]
            },
        )


class LaunchesResource(resource.Resource):
    isLeaf = True

    def render_GET(self, request):
        return json_response(request, {"launches": LAUNCHES})

    def render_POST(self, request):
        raw_body = request.content.read(4097)

        if len(raw_body) > 4096:
            return json_response(
                request,
                {"error": "Request body is too large."},
                status=413,
            )

        try:
            payload = json.loads(raw_body)
        except (ValueError, UnicodeError):
            return json_response(
                request,
                {"error": "Invalid JSON."},
                status=400,
            )

        if not isinstance(payload, dict):
            return json_response(
                request,
                {"error": "Expected a JSON object."},
                status=400,
            )

        mission_id = payload.get("mission_id")

        if not isinstance(mission_id, str) or mission_id not in MISSIONS:
            return json_response(
                request,
                {"error": "Unknown mission."},
                status=400,
            )

        launch = {
            "id": len(LAUNCHES) + 1,
            "mission_id": mission_id,
            "recorded_at": current_time(),
        }
        LAUNCHES.append(launch)
        return json_response(request, launch, status=201)


class ChecklistResource(resource.Resource):
    isLeaf = True

    def render_PUT(self, request):
        raw_body = request.content.read(4097)

        if len(raw_body) > 4096:
            return json_response(
                request,
                {"error": "Request body is too large."},
                status=413,
            )

        try:
            filename = raw_body.decode("utf-8").strip()
        except UnicodeDecodeError:
            return json_response(
                request,
                {"error": "Filename must be UTF-8."},
                status=400,
            )

        if not filename:
            return json_response(
                request,
                {"error": "Checklist filename is required."},
                status=400,
            )

        try:
            checklist_directory = CHECKLIST_ROOT.resolve(strict=True)
            requested_path = Path(filename)

            if requested_path.is_absolute():
                return json_response(
                    request,
                    {"error": "Invalid checklist path."},
                    status=400,
                )

            checklist_path = (
                checklist_directory / requested_path
            ).resolve(strict=True)

            if not checklist_path.is_relative_to(checklist_directory):
                return json_response(
                    request,
                    {"error": "Invalid checklist path."},
                    status=400,
                )

            content = checklist_path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            return json_response(
                request,
                {"error": "Checklist not found."},
                status=404,
            )
        except (OSError, UnicodeError, ValueError, RuntimeError):
            return json_response(
                request,
                {"error": "Checklist cannot be read."},
                status=400,
            )

        request.setHeader(b"content-type", b"text/plain; charset=utf-8")
        request.setHeader(b"x-content-type-options", b"nosniff")
        return content.encode("utf-8")


def main():
    initialize_storage()
    root = IndexResource()
    root.putChild(b"missions", MissionsResource())
    root.putChild(b"launches", LaunchesResource())
    root.putChild(b"checklist", ChecklistResource())

    site = server.Site(root)
    reactor.listenTCP(8170, site, interface="127.0.0.1")
    reactor.run()


if __name__ == "__main__":
    main()
