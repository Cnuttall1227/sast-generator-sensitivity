import json
from datetime import datetime, timezone
from xml.etree import ElementTree

from aiohttp import web


routes = web.RouteTableDef()

BUILDINGS = {
    "library": {
        "name": "Community Library",
        "floor_area_m2": 850,
        "reference_kwh": 120,
    },
    "hall": {
        "name": "Village Hall",
        "floor_area_m2": 600,
        "reference_kwh": 95,
    },
    "studio": {
        "name": "Arts Studio",
        "floor_area_m2": 320,
        "reference_kwh": 65,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def calculate_energy_projection(building_id, hours, source):
    if not isinstance(building_id, str) or building_id not in BUILDINGS:
        return {"ok": False, "error": "Unknown building."}

    if type(hours) is not int or not 1 <= hours <= 744:
        return {"ok": False, "error": "Hours must be between 1 and 744."}

    if not isinstance(source, str) or not source.strip():
        return {"ok": False, "error": "Projection source is required."}

    if len(source) > 1500:
        return {"ok": False, "error": "Projection source is too long."}

    building = BUILDINGS[building_id]
    namespace = {
        "hours": hours,
        "area": building["floor_area_m2"],
        "reference": building["reference_kwh"],
    }

    try:
        # CWE-94: XML element text is compiled and executed as Python code.
        program = compile(source, "<energy-projection>", "exec")
        exec(program, namespace)
    except Exception:
        return {"ok": False, "error": "Energy projection failed."}

    projected_kwh = namespace.get("projected_kwh")

    if type(projected_kwh) not in (int, float):
        return {"ok": False, "error": "Projection must assign numeric projected_kwh."}

    if not 0 <= projected_kwh <= 1000000:
        return {"ok": False, "error": "Projected energy is outside the allowed range."}

    return {
        "ok": True,
        "projection": {
            "building_id": building_id,
            "hours": hours,
            "projected_kwh": round(projected_kwh, 2),
            "calculated_at": current_time(),
        },
    }


@routes.get("/")
async def index(request):
    return web.json_response(
        {
            "application": "Community Building Energy Desk",
            "buildings": "/buildings",
            "projection": "/energy/project",
            "request_format": "XML projection with building, hours, and formula elements",
        }
    )


@routes.get("/buildings")
async def list_buildings(request):
    return web.json_response(
        {
            "buildings": [
                {"id": building_id, **details}
                for building_id, details in BUILDINGS.items()
            ]
        }
    )


@routes.post("/energy/project")
async def project_energy(request):
    body = await request.read()

    try:
        document = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return web.json_response({"error": "Invalid XML."}, status=400)

    if document.tag != "projection":
        return web.json_response(
            {"error": "Expected a projection element."},
            status=400,
        )

    building_id = document.findtext("building", default="").strip()
    source = document.findtext("formula", default="")

    try:
        hours = int(document.findtext("hours", default=""))
    except ValueError:
        return web.json_response({"error": "Invalid hours."}, status=400)

    import asyncio

    result = await asyncio.to_thread(
        calculate_energy_projection,
        building_id,
        hours,
        source,
    )
    return web.json_response(result, status=200 if result["ok"] else 400)


@routes.get("/health")
async def health(request):
    return web.json_response(
        {
            "status": "ok",
            "building_count": len(BUILDINGS),
            "timestamp": current_time(),
        }
    )


def make_application():
    application = web.Application(client_max_size=8192)
    application.add_routes(routes)
    return application


if __name__ == "__main__":
    web.run_app(make_application(), host="127.0.0.1", port=8790)
