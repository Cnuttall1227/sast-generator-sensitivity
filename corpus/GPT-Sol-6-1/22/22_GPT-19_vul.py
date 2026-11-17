import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from pyramid.config import Configurator
from pyramid.response import Response
from wsgiref.simple_server import make_server


DATA_ROOT = Path(__file__).resolve().parent / "textile_workshop"
PATTERN_ROOT = DATA_ROOT / "weaving_patterns"

LOOMS = {
    "table": {
        "name": "Table Loom",
        "shafts": 4,
        "available": True,
    },
    "floor": {
        "name": "Floor Loom",
        "shafts": 8,
        "available": True,
    },
    "rigid": {
        "name": "Rigid Heddle Loom",
        "shafts": 2,
        "available": False,
    },
}

SAMPLE_PATTERNS = {
    "plain.txt": (
        "Plain weave sampler\n"
        "Alternate over and under across each row.\n"
    ),
    "twill.txt": (
        "Twill sampler\n"
        "Shift the interlacement by one thread per row.\n"
    ),
}

RESERVATIONS = []


def initialize_storage():
    PATTERN_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_PATTERNS.items():
        destination = PATTERN_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(payload, status=200):
    return Response(
        body=json.dumps(payload).encode("utf-8"),
        status=status,
        content_type="application/json",
        charset="utf-8",
    )


def index(request):
    return json_response(
        {
            "application": "Textile Workshop Loom Desk",
            "looms": "/looms",
            "reservations": "/reservations",
            "pattern_preview": "/patterns/preview",
            "selector": "POST XML: <preview document='plain.txt'/>",
        }
    )


def list_looms(request):
    return json_response(
        {
            "looms": [
                {"id": loom_id, **details}
                for loom_id, details in LOOMS.items()
            ]
        }
    )


def list_reservations(request):
    return json_response({"reservations": RESERVATIONS})


def reserve_loom(request):
    try:
        payload = request.json_body
    except (ValueError, UnicodeError):
        return json_response({"error": "Invalid JSON."}, status=400)

    if not isinstance(payload, dict):
        return json_response({"error": "Expected an object."}, status=400)

    loom_id = payload.get("loom_id")
    weaver = payload.get("weaver")

    if not isinstance(loom_id, str) or loom_id not in LOOMS:
        return json_response({"error": "Unknown loom."}, status=400)

    if not LOOMS[loom_id]["available"]:
        return json_response({"error": "Loom is unavailable."}, status=409)

    if not isinstance(weaver, str) or not weaver.strip():
        return json_response({"error": "Weaver name is required."}, status=400)

    reservation = {
        "id": len(RESERVATIONS) + 1,
        "loom_id": loom_id,
        "weaver": weaver,
        "created_at": current_time(),
    }
    RESERVATIONS.append(reservation)
    return json_response(reservation, status=201)


def preview_pattern(request):
    if len(request.body) > 4096:
        return json_response({"error": "Request body too large."}, status=413)

    try:
        selection = ElementTree.fromstring(request.body)
    except ElementTree.ParseError:
        return json_response({"error": "Invalid XML."}, status=400)

    if selection.tag != "preview":
        return json_response({"error": "Expected a preview element."}, status=400)

    filename = selection.get("document", "plain.txt")

    if not filename.strip():
        return json_response({"error": "Document is required."}, status=400)

    # CWE-22: an XML attribute supplies an unchecked filesystem path.
    pattern_path = PATTERN_ROOT / filename

    try:
        content = pattern_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return json_response({"error": "Pattern not found."}, status=404)
    except (OSError, UnicodeError, ValueError):
        return json_response({"error": "Pattern cannot be read."}, status=400)

    return Response(
        body=content.encode("utf-8"),
        content_type="text/plain",
        charset="utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def make_application():
    initialize_storage()

    with Configurator() as configuration:
        configuration.add_route("index", "/")
        configuration.add_route("looms", "/looms")
        configuration.add_route("reservations", "/reservations")
        configuration.add_route("preview", "/patterns/preview")
        configuration.add_view(index, route_name="index", request_method="GET")
        configuration.add_view(list_looms, route_name="looms", request_method="GET")
        configuration.add_view(
            list_reservations,
            route_name="reservations",
            request_method="GET",
        )
        configuration.add_view(
            reserve_loom,
            route_name="reservations",
            request_method="POST",
        )
        configuration.add_view(
            preview_pattern,
            route_name="preview",
            request_method="POST",
        )
        return configuration.make_wsgi_app()


def main():
    parser = argparse.ArgumentParser(description="Textile workshop loom desk.")
    parser.add_argument("--port", type=int, default=8210)
    args = parser.parse_args()

    with make_server("127.0.0.1", args.port, make_application()) as server:
        print(f"Textile workshop listening on 127.0.0.1:{args.port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
