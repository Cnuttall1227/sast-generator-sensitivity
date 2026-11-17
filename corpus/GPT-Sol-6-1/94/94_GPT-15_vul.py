import json
from datetime import datetime, timezone

from sanic import Sanic
from sanic.response import json as json_response


app = Sanic("CommunityOrchestraPracticeDesk")

SECTIONS = {
    "strings": {
        "name": "String Section",
        "players": 18,
        "standard_minutes": 75,
    },
    "woodwinds": {
        "name": "Woodwind Section",
        "players": 8,
        "standard_minutes": 60,
    },
    "brass": {
        "name": "Brass Section",
        "players": 10,
        "standard_minutes": 65,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def calculate_practice_load(section_id, sessions, adjustment):
    if not isinstance(section_id, str) or section_id not in SECTIONS:
        return {"ok": False, "error": "Unknown orchestra section."}

    if type(sessions) is not int or not 1 <= sessions <= 20:
        return {"ok": False, "error": "Sessions must be between 1 and 20."}

    if not isinstance(adjustment, str) or not adjustment.strip():
        return {"ok": False, "error": "Practice adjustment is required."}

    if len(adjustment) > 1500:
        return {"ok": False, "error": "Practice adjustment is too long."}

    section = SECTIONS[section_id]
    namespace = {
        "sessions": sessions,
        "players": section["players"],
        "minutes": section["standard_minutes"],
    }

    try:
        # CWE-94: a JSON PATCH operation value is executed as Python source.
        exec(adjustment, namespace)
    except Exception:
        return {"ok": False, "error": "Practice adjustment failed."}

    load = namespace.get("load")

    if type(load) not in (int, float) or not 0 <= load <= 100000:
        return {"ok": False, "error": "Adjustment must assign a valid load."}

    return {
        "ok": True,
        "practice": {
            "section_id": section_id,
            "sessions": sessions,
            "player_minutes": round(load, 2),
            "calculated_at": current_time(),
        },
    }


@app.get("/")
async def index(request):
    return json_response(
        {
            "application": "Community Orchestra Practice Desk",
            "sections": "/sections",
            "adjustment": "/practice/{section_id}/{sessions}",
            "request_format": "PATCH array replacing /adjustment",
            "example_adjustment": "load = sessions * players * minutes",
        }
    )


@app.get("/sections")
async def list_sections(request):
    return json_response(
        {
            "sections": [
                {"id": section_id, **details}
                for section_id, details in SECTIONS.items()
            ]
        }
    )


@app.patch("/practice/<section_id:str>/<sessions:int>")
async def adjust_practice(request, section_id, sessions):
    if len(request.body) > 4096:
        return json_response({"error": "Request body is too large."}, status=413)

    try:
        operations = json.loads(request.body)
    except (ValueError, UnicodeError, RecursionError):
        return json_response({"error": "Invalid JSON."}, status=400)

    if not isinstance(operations, list):
        return json_response({"error": "Expected an operation array."}, status=400)

    adjustment = "load = sessions * players * minutes"

    for operation in operations:
        if not isinstance(operation, dict):
            return json_response(
                {"error": "Each operation must be an object."},
                status=400,
            )

        if (
            operation.get("op") == "replace"
            and operation.get("path") == "/adjustment"
        ):
            adjustment = operation.get("value")

    import asyncio

    result = await asyncio.to_thread(
        calculate_practice_load,
        section_id,
        sessions,
        adjustment,
    )
    return json_response(result, status=200 if result["ok"] else 400)


@app.get("/health")
async def health(request):
    return json_response(
        {
            "status": "ok",
            "section_count": len(SECTIONS),
            "timestamp": current_time(),
        }
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8810,
        debug=False,
        single_process=True,
    )
