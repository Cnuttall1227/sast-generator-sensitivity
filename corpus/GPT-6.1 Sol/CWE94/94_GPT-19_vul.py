import json
from datetime import datetime, timezone
from urllib.parse import parse_qs

from werkzeug.serving import run_simple
from werkzeug.wrappers import Request, Response


BOATS = {
    "canoe": {
        "name": "Two-Person Canoe",
        "hourly_rate": 14,
        "deposit": 25,
    },
    "kayak": {
        "name": "Single Kayak",
        "hourly_rate": 10,
        "deposit": 20,
    },
    "rowboat": {
        "name": "Family Rowboat",
        "hourly_rate": 18,
        "deposit": 30,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(payload, status=200):
    return Response(
        json.dumps(payload),
        status=status,
        content_type="application/json; charset=utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def calculate_rental_quote(boat_id, hours, formula):
    if not isinstance(boat_id, str) or boat_id not in BOATS:
        return {"ok": False, "error": "Unknown boat."}

    if type(hours) is not int or not 1 <= hours <= 12:
        return {"ok": False, "error": "Hours must be between 1 and 12."}

    if not isinstance(formula, str) or not formula.strip():
        return {"ok": False, "error": "Quote formula is required."}

    if len(formula) > 500:
        return {"ok": False, "error": "Quote formula is too long."}

    boat = BOATS[boat_id]

    try:
        # CWE-94: a URL-encoded cookie field is evaluated as Python code.
        total = eval(
            formula,
            {"__builtins__": __builtins__},
            {
                "hours": hours,
                "hourly_rate": boat["hourly_rate"],
                "deposit": boat["deposit"],
            },
        )
    except Exception:
        return {"ok": False, "error": "Quote formula failed."}

    if type(total) not in (int, float) or not 0 <= total <= 10000:
        return {"ok": False, "error": "Quote total is outside the allowed range."}

    return {
        "ok": True,
        "quote": {
            "boat_id": boat_id,
            "hours": hours,
            "total": round(total, 2),
            "calculated_at": current_time(),
        },
    }


@Request.application
def application(request):
    request.max_content_length = 4096

    if request.method == "GET" and request.path == "/":
        return json_response(
            {
                "application": "Community Boathouse Rental Desk",
                "boats": "/boats",
                "quote": "/rentals/quote",
                "formula_cookie": "rental_preferences",
                "cookie_format": "formula=<URL-encoded expression>",
            }
        )

    if request.method == "GET" and request.path == "/boats":
        return json_response(
            {
                "boats": [
                    {"id": boat_id, **details}
                    for boat_id, details in BOATS.items()
                ]
            }
        )

    if request.method == "POST" and request.path == "/rentals/quote":
        payload = request.get_json(silent=True)

        if not isinstance(payload, dict):
            return json_response({"error": "Expected a JSON object."}, 400)

        cookie = request.cookies.get(
            "rental_preferences",
            "formula=hours%20%2A%20hourly_rate%20%2B%20deposit",
        )

        try:
            preferences = parse_qs(cookie, max_num_fields=10)
        except ValueError:
            return json_response({"error": "Invalid rental preferences."}, 400)

        formula = preferences.get("formula", ["hours * hourly_rate + deposit"])[0]
        result = calculate_rental_quote(
            payload.get("boat_id"),
            payload.get("hours"),
            formula,
        )
        return json_response(result, 200 if result["ok"] else 400)

    if request.method == "GET" and request.path == "/health":
        return json_response(
            {
                "status": "ok",
                "boat_count": len(BOATS),
                "timestamp": current_time(),
            }
        )

    return json_response({"error": "Endpoint not found."}, 404)


if __name__ == "__main__":
    run_simple(
        "127.0.0.1",
        8830,
        application,
        use_debugger=False,
        use_reloader=False,
    )
