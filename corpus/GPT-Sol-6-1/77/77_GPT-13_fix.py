import json
import subprocess
from datetime import datetime, timezone

from aiohttp import web


app_routes = web.RouteTableDef()

COLLECTIONS = {
    "interviews": {
        "title": "Neighborhood Interviews",
        "recordings": 32,
        "coordinator": "Alex",
    },
    "performances": {
        "title": "Community Performances",
        "recordings": 18,
        "coordinator": "Morgan",
    },
    "lectures": {
        "title": "Public Lectures",
        "recordings": 25,
        "coordinator": "Jamie",
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def inspect_storage_volume(volume_label):
    if not isinstance(volume_label, str) or not volume_label.strip():
        return {"ok": False, "error": "Volume label is required."}

    if len(volume_label) > 120:
        return {"ok": False, "error": "Volume label is too long."}

    if "\x00" in volume_label:
        return {"ok": False, "error": "Invalid volume label."}

    try:
        result = subprocess.run(
            ["findmnt", "--json", "--source", f"LABEL={volume_label}"],
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Volume inspection timed out."}
    except (OSError, ValueError):
        return {"ok": False, "error": "Volume inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "label": volume_label,
        "mount_details": result.stdout[:4000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


@app_routes.get("/")
async def index(request):
    return web.json_response(
        {
            "application": "Community Media Storage Desk",
            "collections": "/collections",
            "transfers": "/transfers",
            "volume_check": "/storage/inspect",
            "selector": "multipart text field volume_label",
        }
    )


@app_routes.get("/collections")
async def list_collections(request):
    return web.json_response(
        {
            "collections": [
                {"id": collection_id, **details}
                for collection_id, details in COLLECTIONS.items()
            ]
        }
    )


@app_routes.get("/transfers")
async def list_transfers(request):
    return web.json_response({"transfers": request.app["transfers"]})


@app_routes.post("/transfers")
async def record_transfer(request):
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        return web.json_response({"error": "Invalid JSON."}, status=400)

    if not isinstance(payload, dict):
        return web.json_response({"error": "Expected an object."}, status=400)

    collection_id = payload.get("collection_id")
    operator = payload.get("operator")

    if not isinstance(collection_id, str) or collection_id not in COLLECTIONS:
        return web.json_response({"error": "Unknown collection."}, status=400)

    if not isinstance(operator, str) or not operator.strip():
        return web.json_response({"error": "Operator is required."}, status=400)

    transfers = request.app["transfers"]
    transfer = {
        "id": len(transfers) + 1,
        "collection_id": collection_id,
        "operator": operator,
        "recorded_at": current_time(),
    }
    transfers.append(transfer)
    return web.json_response(transfer, status=201)


@app_routes.post("/storage/inspect")
async def check_volume(request):
    if request.content_type != "multipart/form-data":
        return web.json_response(
            {"error": "Expected multipart form data."},
            status=400,
        )

    reader = await request.multipart()
    part = await reader.next()

    if part is None or part.name != "volume_label" or part.filename:
        return web.json_response(
            {"error": "A volume_label text field is required."},
            status=400,
        )

    data = bytearray()

    while True:
        chunk = await part.read_chunk()
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > 512:
            return web.json_response(
                {"error": "Volume label field is too large."},
                status=400,
            )

    try:
        volume_label = data.decode("utf-8")
    except UnicodeDecodeError:
        return web.json_response({"error": "Invalid UTF-8."}, status=400)

    import asyncio

    result = await asyncio.to_thread(inspect_storage_volume, volume_label)
    return web.json_response(result)


def make_application():
    application = web.Application(client_max_size=8192)
    application["transfers"] = []
    application.add_routes(app_routes)
    return application


if __name__ == "__main__":
    web.run_app(make_application(), host="127.0.0.1", port=8310)
