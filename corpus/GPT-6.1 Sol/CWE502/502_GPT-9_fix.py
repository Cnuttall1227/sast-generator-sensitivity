import json
import pickle
from datetime import datetime, timezone

from bottle import Bottle, request, response, run


app = Bottle()

GALLERIES = {
    "landscape": {
        "title": "Landscape Photography",
        "floor": 1,
        "capacity": 30,
    },
    "portrait": {
        "title": "Contemporary Portraits",
        "floor": 2,
        "capacity": 20,
    },
    "abstract": {
        "title": "Abstract Perspectives",
        "floor": 2,
        "capacity": 25,
    },
}

VISITS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(payload, status=200):
    response.status = status
    response.content_type = "application/json; charset=utf-8"
    response.set_header("X-Content-Type-Options", "nosniff")
    return json.dumps(payload)


def restore_tour_state(serialized_state):
    if not isinstance(serialized_state, bytes) or not serialized_state:
        return {"ok": False, "error": "Tour state is required."}

    if len(serialized_state) > 16384:
        return {"ok": False, "error": "Tour state is too large."}

    # Clients must send UTF-8 JSON instead of pickle.
    try:
        state = json.loads(serialized_state.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return {"ok": False, "error": "Tour state must contain UTF-8 JSON."}

    if not isinstance(state, dict):
        return {"ok": False, "error": "Tour state must contain an object."}

    gallery_id = state.get("gallery_id")
    guide = state.get("guide")
    group_size = state.get("group_size")

    if not isinstance(gallery_id, str) or gallery_id not in GALLERIES:
        return {"ok": False, "error": "Unknown gallery."}

    if not isinstance(guide, str) or not guide.strip():
        return {"ok": False, "error": "Guide name is required."}

    if type(group_size) is not int:
        return {"ok": False, "error": "Group size must be an integer."}

    if not 1 <= group_size <= GALLERIES[gallery_id]["capacity"]:
        return {"ok": False, "error": "Group size exceeds gallery capacity."}

    return {
        "ok": True,
        "state": {
            "gallery_id": gallery_id,
            "guide": guide,
            "group_size": group_size,
            "restored_at": current_time(),
        },
    }


@app.get("/")
def index():
    return json_response(
        {
            "application": "Photography Gallery Tour Desk",
            "galleries": "/galleries",
            "visits": "/visits",
            "restore": "/tours/state",
            "restore_format": "PUT binary serialized tour state",
        }
    )


@app.get("/galleries")
def list_galleries():
    return json_response(
        {
            "galleries": [
                {"id": gallery_id, **details}
                for gallery_id, details in GALLERIES.items()
            ]
        }
    )


@app.get("/visits")
def list_visits():
    return json_response({"visits": VISITS})


@app.post("/visits")
def record_visit():
    gallery_id = request.forms.getunicode("gallery_id", "")
    visitor = request.forms.getunicode("visitor", "")

    if gallery_id not in GALLERIES:
        return json_response({"error": "Unknown gallery."}, status=400)

    if not visitor.strip():
        return json_response({"error": "Visitor name is required."}, status=400)

    visit = {
        "id": len(VISITS) + 1,
        "gallery_id": gallery_id,
        "visitor": visitor,
        "recorded_at": current_time(),
    }
    VISITS.append(visit)
    return json_response(visit, status=201)


@app.put("/tours/state")
def import_tour_state():
    serialized_state = request.body.read(16385)
    result = restore_tour_state(serialized_state)
    return json_response(result, status=200 if result["ok"] else 400)


if __name__ == "__main__":
    run(
        app=app,
        host="127.0.0.1",
        port=8430,
        debug=False,
        reloader=False,
    )
