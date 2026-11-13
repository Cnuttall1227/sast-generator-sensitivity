import json
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web


DATA_ROOT = Path(__file__).resolve().parent / "bicycle_workshop"
MANUAL_ROOT = DATA_ROOT / "manuals"

SERVICES = {
    "brakes": {
        "name": "Brake Adjustment",
        "duration_minutes": 30,
        "price": 25,
    },
    "gears": {
        "name": "Gear Indexing",
        "duration_minutes": 40,
        "price": 35,
    },
    "inspection": {
        "name": "Safety Inspection",
        "duration_minutes": 20,
        "price": 15,
    },
}

SAMPLE_MANUALS = {
    "brakes.txt": (
        "Brake Adjustment\n"
        "Inspect pads and cables before adjusting tension.\n"
        "Verify wheel rotation and braking performance.\n"
    ),
    "gears.txt": (
        "Gear Indexing\n"
        "Inspect the derailleur hanger and cable condition.\n"
        "Adjust indexing and verify all gear positions.\n"
    ),
    "inspection.txt": (
        "Safety Inspection\n"
        "Check tires, wheels, steering, and fasteners.\n"
        "Record any components requiring replacement.\n"
    ),
}


def initialize_storage():
    MANUAL_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_MANUALS.items():
        destination = MANUAL_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


async def index(request):
    return web.json_response(
        {
            "application": "Bicycle Workshop Scheduler",
            "services": "/services",
            "appointments": "/appointments",
            "manual_upload": "/manuals/preview",
        }
    )


async def health(request):
    return web.json_response(
        {
            "status": "ok",
            "timestamp": current_time(),
        }
    )


async def list_services(request):
    return web.json_response(
        {
            "services": [
                {"id": service_id, **details}
                for service_id, details in SERVICES.items()
            ]
        }
    )


async def create_appointment(request):
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON."}, status=400)

    if not isinstance(payload, dict):
        return web.json_response({"error": "Expected an object."}, status=400)

    service_id = payload.get("service_id")
    customer = payload.get("customer")

    if not isinstance(service_id, str) or service_id not in SERVICES:
        return web.json_response({"error": "Unknown service."}, status=400)

    if not isinstance(customer, str) or not customer.strip():
        return web.json_response({"error": "Customer is required."}, status=400)

    appointments = request.app["appointments"]
    appointment = {
        "id": len(appointments) + 1,
        "service_id": service_id,
        "customer": customer,
        "created_at": current_time(),
    }
    appointments.append(appointment)
    return web.json_response(appointment, status=201)


async def list_appointments(request):
    return web.json_response(
        {"appointments": request.app["appointments"]}
    )


async def preview_manual(request):
    if request.content_type != "multipart/form-data":
        return web.json_response(
            {"error": "Expected a multipart form."},
            status=400,
        )

    reader = await request.multipart()
    part = await reader.next()

    if part is None or part.name != "manual" or not part.filename:
        return web.json_response(
            {"error": "A manual file part is required."},
            status=400,
        )

    try:
        manual_directory = MANUAL_ROOT.resolve(strict=True)
        requested_path = Path(part.filename)

        if requested_path.is_absolute():
            return web.json_response(
                {"error": "Invalid manual path."},
                status=400,
            )

        manual_path = (manual_directory / requested_path).resolve(
            strict=True
        )

        if not manual_path.is_relative_to(manual_directory):
            return web.json_response(
                {"error": "Invalid manual path."},
                status=400,
            )

        content = manual_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return web.json_response(
            {"error": "Manual not found."},
            status=404,
        )
    except (OSError, UnicodeError, ValueError, RuntimeError):
        return web.json_response(
            {"error": "Manual cannot be previewed."},
            status=400,
        )

    return web.Response(
        text=content,
        content_type="text/plain",
        charset="utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def make_application():
    initialize_storage()
    app = web.Application(client_max_size=1024 * 1024)
    app["appointments"] = []
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/services", list_services)
    app.router.add_get("/appointments", list_appointments)
    app.router.add_post("/appointments", create_appointment)
    app.router.add_post("/manuals/preview", preview_manual)
    return app


if __name__ == "__main__":
    web.run_app(make_application(), host="127.0.0.1", port=8120)
