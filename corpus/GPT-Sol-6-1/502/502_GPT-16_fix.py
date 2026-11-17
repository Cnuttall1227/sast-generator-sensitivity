import json
import pickle
from datetime import datetime, timezone
from io import BytesIO

from aiohttp import web


routes = web.RouteTableDef()

ROUTES = {
    "canal": {
        "name": "Canal Heritage Ride",
        "distance_km": 12,
        "capacity": 18,
    },
    "orchard": {
        "name": "Orchard Loop Ride",
        "distance_km": 20,
        "capacity": 14,
    },
    "village": {
        "name": "Village Discovery Ride",
        "distance_km": 8,
        "capacity": 24,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def import_ride_manifest(serialized):
    if not isinstance(serialized, bytes) or not serialized:
        return {"ok": False, "error": "Ride manifest is required."}

    if len(serialized) > 16384:
        return {"ok": False, "error": "Ride manifest is too large."}

    # Uploads must contain UTF-8 JSON instead of pickle.
    try:
        manifest = json.loads(serialized.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return {"ok": False, "error": "Ride manifest must contain UTF-8 JSON."}

    if not isinstance(manifest, dict):
        return {"ok": False, "error": "Manifest must contain an object."}

    route_id = manifest.get("route_id")
    leader = manifest.get("leader")
    riders = manifest.get("riders")

    if not isinstance(route_id, str) or route_id not in ROUTES:
        return {"ok": False, "error": "Unknown ride route."}

    if not isinstance(leader, str) or not leader.strip():
        return {"ok": False, "error": "Ride leader is required."}

    if type(riders) is not int or not 1 <= riders <= ROUTES[route_id]["capacity"]:
        return {"ok": False, "error": "Invalid rider count."}

    return {
        "ok": True,
        "manifest": {
            "route_id": route_id,
            "leader": leader,
            "riders": riders,
            "imported_at": current_time(),
        },
    }


@routes.get("/")
async def index(request):
    return web.json_response(
        {
            "application": "Community Cycling Ride Desk",
            "routes": "/routes",
            "checkins": "/checkins",
            "import": "/rides/import",
            "selector": "multipart file field ride_manifest",
        }
    )


@routes.get("/routes")
async def list_routes(request):
    return web.json_response(
        {
            "routes": [
                {"id": route_id, **details}
                for route_id, details in ROUTES.items()
            ]
        }
    )


@routes.get("/checkins")
async def list_checkins(request):
    return web.json_response({"checkins": request.app["checkins"]})


@routes.post("/checkins")
async def record_checkin(request):
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        return web.json_response({"error": "Invalid JSON."}, status=400)

    if not isinstance(payload, dict):
        return web.json_response({"error": "Expected an object."}, status=400)

    route_id = payload.get("route_id")
    rider = payload.get("rider")

    if not isinstance(route_id, str) or route_id not in ROUTES:
        return web.json_response({"error": "Unknown route."}, status=400)

    if not isinstance(rider, str) or not rider.strip():
        return web.json_response({"error": "Rider is required."}, status=400)

    checkins = request.app["checkins"]
    checkin = {
        "id": len(checkins) + 1,
        "route_id": route_id,
        "rider": rider,
        "checked_in_at": current_time(),
    }
    checkins.append(checkin)
    return web.json_response(checkin, status=201)


@routes.post("/rides/import")
async def upload_manifest(request):
    if request.content_type != "multipart/form-data":
        return web.json_response(
            {"error": "Expected multipart form data."},
            status=400,
        )

    reader = await request.multipart()
    part = await reader.next()

    if part is None or part.name != "ride_manifest" or not part.filename:
        return web.json_response(
            {"error": "A ride_manifest file is required."},
            status=400,
        )

    data = bytearray()

    while True:
        chunk = await part.read_chunk()
        if not chunk:
            break

        data.extend(chunk)
        if len(data) > 16384:
            return web.json_response(
                {"error": "Ride manifest is too large."},
                status=413,
            )

    result = import_ride_manifest(bytes(data))
    return web.json_response(result, status=201 if result["ok"] else 400)


def make_application():
    application = web.Application(client_max_size=32768)
    application["checkins"] = []
    application.add_routes(routes)
    return application


if __name__ == "__main__":
    web.run_app(make_application(), host="127.0.0.1", port=8490)
