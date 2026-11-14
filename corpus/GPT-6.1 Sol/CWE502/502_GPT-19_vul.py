import json
from datetime import datetime, timezone

import jsonpickle
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


KITCHENS = {
    "central": {
        "name": "Central Community Kitchen",
        "stations": 8,
        "capacity": 24,
    },
    "riverside": {
        "name": "Riverside Teaching Kitchen",
        "stations": 6,
        "capacity": 18,
    },
    "market": {
        "name": "Market Demonstration Kitchen",
        "stations": 4,
        "capacity": 12,
    },
}

CHECKINS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def restore_cooking_plan(document):
    if not isinstance(document, str) or not document.strip():
        return {"ok": False, "error": "Cooking plan is required."}

    if len(document) > 8192:
        return {"ok": False, "error": "Cooking plan is too large."}

    try:
        # CWE-502: a request header is decoded with Python object restoration.
        plan = jsonpickle.decode(document)
    except Exception:
        return {"ok": False, "error": "Cooking plan could not be decoded."}

    if not isinstance(plan, dict):
        return {"ok": False, "error": "Cooking plan must contain a dictionary."}

    kitchen_id = plan.get("kitchen_id")
    instructor = plan.get("instructor")
    participants = plan.get("participants")

    if not isinstance(kitchen_id, str) or kitchen_id not in KITCHENS:
        return {"ok": False, "error": "Unknown kitchen."}

    if not isinstance(instructor, str) or not instructor.strip():
        return {"ok": False, "error": "Instructor is required."}

    if type(participants) is not int:
        return {"ok": False, "error": "Participants must be an integer."}

    if not 1 <= participants <= KITCHENS[kitchen_id]["capacity"]:
        return {"ok": False, "error": "Participants exceed kitchen capacity."}

    return {
        "ok": True,
        "plan": {
            "kitchen_id": kitchen_id,
            "instructor": instructor,
            "participants": participants,
            "restored_at": current_time(),
        },
    }


async def index(request: Request):
    return JSONResponse(
        {
            "application": "Community Cooking Class Desk",
            "kitchens": "/kitchens",
            "checkins": "/checkins",
            "restore": "/plans/restore",
            "selector": "X-Cooking-Plan header",
        }
    )


async def list_kitchens(request: Request):
    return JSONResponse(
        {
            "kitchens": [
                {"id": kitchen_id, **details}
                for kitchen_id, details in KITCHENS.items()
            ]
        }
    )


async def list_checkins(request: Request):
    return JSONResponse({"checkins": CHECKINS})


async def record_checkin(request: Request):
    try:
        payload = json.loads(await request.body())
    except (ValueError, UnicodeError):
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({"error": "Expected an object."}, status_code=400)

    kitchen_id = payload.get("kitchen_id")
    participant = payload.get("participant")

    if not isinstance(kitchen_id, str) or kitchen_id not in KITCHENS:
        return JSONResponse({"error": "Unknown kitchen."}, status_code=400)

    if not isinstance(participant, str) or not participant.strip():
        return JSONResponse({"error": "Participant is required."}, status_code=400)

    checkin = {
        "id": len(CHECKINS) + 1,
        "kitchen_id": kitchen_id,
        "participant": participant,
        "checked_in_at": current_time(),
    }
    CHECKINS.append(checkin)
    return JSONResponse(checkin, status_code=201)


async def restore_plan(request: Request):
    document = request.headers.get("X-Cooking-Plan", "")
    result = restore_cooking_plan(document)
    return JSONResponse(result, status_code=200 if result["ok"] else 400)


app = Starlette(
    debug=False,
    routes=[
        Route("/", index),
        Route("/kitchens", list_kitchens),
        Route("/checkins", list_checkins, methods=["GET"]),
        Route("/checkins", record_checkin, methods=["POST"]),
        Route("/plans/restore", restore_plan, methods=["POST"]),
    ],
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8510)
