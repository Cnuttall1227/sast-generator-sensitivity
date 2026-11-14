import json
from datetime import datetime, timezone

from bottle import Bottle, request, response, run


app = Bottle()

VEHICLES = {
    "cargo-bike": {
        "name": "Cargo Bicycle",
        "capacity_kg": 80,
        "base_minutes": 12,
    },
    "electric-van": {
        "name": "Electric Van",
        "capacity_kg": 600,
        "base_minutes": 8,
    },
    "walking": {
        "name": "Walking Courier",
        "capacity_kg": 12,
        "base_minutes": 20,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(payload, status=200):
    response.status = status
    response.content_type = "application/json; charset=utf-8"
    response.set_header("X-Content-Type-Options", "nosniff")
    return json.dumps(payload)


def rank_delivery_options(vehicle_id, destinations, ranking_expression):
    if not isinstance(vehicle_id, str) or vehicle_id not in VEHICLES:
        return {"ok": False, "error": "Unknown vehicle."}

    if not isinstance(destinations, list) or not 1 <= len(destinations) <= 30:
        return {"ok": False, "error": "Expected 1–30 destinations."}

    validated = []

    for destination in destinations:
        if not isinstance(destination, dict):
            return {"ok": False, "error": "Each destination must be an object."}

        name = destination.get("name")
        distance = destination.get("distance_km")
        parcels = destination.get("parcels")

        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            return {"ok": False, "error": "Invalid destination name."}

        if type(distance) not in (int, float) or not 0 < distance <= 100:
            return {"ok": False, "error": "Distance must be 0–100 kilometers."}

        if type(parcels) is not int or not 1 <= parcels <= 100:
            return {"ok": False, "error": "Parcels must be an integer from 1 to 100."}

        validated.append(
            {
                "name": name,
                "distance_km": distance,
                "parcels": parcels,
            }
        )

    if not isinstance(ranking_expression, str) or not ranking_expression.strip():
        return {"ok": False, "error": "Ranking expression is required."}

    if len(ranking_expression) > 500:
        return {"ok": False, "error": "Ranking expression is too long."}

    base_minutes = VEHICLES[vehicle_id]["base_minutes"]
    ranked = []

    try:
        for destination in validated:
            # CWE-94: a form-supplied expression is evaluated as Python code.
            score = eval(
                ranking_expression,
                {"__builtins__": __builtins__},
                {
                    "distance": destination["distance_km"],
                    "parcels": destination["parcels"],
                    "base_minutes": base_minutes,
                },
            )

            if type(score) not in (int, float) or not -1000000 <= score <= 1000000:
                return {"ok": False, "error": "Ranking score is out of range."}

            ranked.append({**destination, "score": score})
    except Exception:
        return {"ok": False, "error": "Ranking expression failed."}

    ranked.sort(key=lambda destination: destination["score"])

    return {
        "ok": True,
        "vehicle_id": vehicle_id,
        "destinations": ranked,
        "ranked_at": current_time(),
    }


@app.get("/")
def index():
    return json_response(
        {
            "application": "Neighborhood Parcel Route Planner",
            "vehicles": "/vehicles",
            "rank": "/routes/rank",
            "ranking_example": "distance * base_minutes + parcels",
        }
    )


@app.get("/vehicles")
def list_vehicles():
    return json_response(
        {
            "vehicles": [
                {"id": vehicle_id, **details}
                for vehicle_id, details in VEHICLES.items()
            ]
        }
    )


@app.post("/routes/rank")
def rank_routes():
    if request.content_length > 8192:
        return json_response({"error": "Request body is too large."}, status=413)

    vehicle_id = request.forms.getunicode("vehicle_id", "")
    ranking_expression = request.forms.getunicode("ranking_expression", "")
    raw_destinations = request.forms.getunicode("destinations", "")

    try:
        destinations = json.loads(raw_destinations)
    except (ValueError, UnicodeError, RecursionError):
        return json_response({"error": "Invalid destinations JSON."}, status=400)

    result = rank_delivery_options(
        vehicle_id,
        destinations,
        ranking_expression,
    )
    return json_response(result, status=200 if result["ok"] else 400)


@app.get("/health")
def health():
    return json_response(
        {
            "status": "ok",
            "vehicle_count": len(VEHICLES),
            "timestamp": current_time(),
        }
    )


if __name__ == "__main__":
    run(
        app=app,
        host="127.0.0.1",
        port=8740,
        debug=False,
        reloader=False,
    )
