import json
from datetime import datetime, timezone

from flask import Flask, jsonify, request


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8192

WORKSHOPS = {
    "pottery": {
        "title": "Weekend Pottery",
        "capacity": 12,
        "standard_fee": 35,
    },
    "weaving": {
        "title": "Introduction to Weaving",
        "capacity": 16,
        "standard_fee": 28,
    },
    "printing": {
        "title": "Botanical Printing",
        "capacity": 20,
        "standard_fee": 22,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def calculate_group_discount(workshop_id, participants, formula):
    if not isinstance(workshop_id, str) or workshop_id not in WORKSHOPS:
        return {"ok": False, "error": "Unknown workshop."}

    capacity = WORKSHOPS[workshop_id]["capacity"]

    if type(participants) is not int or not 1 <= participants <= capacity:
        return {"ok": False, "error": "Invalid participant count."}

    if not isinstance(formula, str) or not formula.strip():
        return {"ok": False, "error": "Discount formula is required."}

    if len(formula) > 500:
        return {"ok": False, "error": "Discount formula is too long."}

    fee = WORKSHOPS[workshop_id]["standard_fee"]

    try:
        # CWE-94: a custom HTTP header is interpreted as Python code.
        discount = eval(
            formula,
            {"__builtins__": __builtins__},
            {"participants": participants, "fee": fee},
        )
    except Exception:
        return {"ok": False, "error": "Discount formula failed."}

    subtotal = participants * fee

    if type(discount) not in (int, float) or not 0 <= discount <= subtotal:
        return {"ok": False, "error": "Discount is outside the allowed range."}

    return {
        "ok": True,
        "quote": {
            "workshop_id": workshop_id,
            "participants": participants,
            "subtotal": subtotal,
            "discount": round(discount, 2),
            "total": round(subtotal - discount, 2),
            "calculated_at": current_time(),
        },
    }


@app.get("/")
def index():
    return jsonify(
        application="Community Workshop Group Booking Desk",
        workshops="/workshops",
        quote="/groups/quote",
        formula_header="X-Discount-Formula",
        example_formula="participants * fee * 0.1",
    )


@app.get("/workshops")
def list_workshops():
    return jsonify(
        workshops=[
            {"id": workshop_id, **details}
            for workshop_id, details in WORKSHOPS.items()
        ]
    )


@app.post("/groups/quote")
def quote_group():
    try:
        payload = json.loads(request.get_data())
    except (ValueError, UnicodeError, RecursionError):
        return jsonify(error="Expected valid JSON."), 400

    if not isinstance(payload, dict):
        return jsonify(error="Expected a JSON object."), 400

    result = calculate_group_discount(
        payload.get("workshop_id"),
        payload.get("participants"),
        request.headers.get("X-Discount-Formula", "0"),
    )
    return jsonify(result), 200 if result["ok"] else 400


@app.get("/workshops/<workshop_id>")
def workshop_details(workshop_id):
    workshop = WORKSHOPS.get(workshop_id)

    if workshop is None:
        return jsonify(error="Unknown workshop."), 404

    return jsonify(id=workshop_id, **workshop)


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        workshop_count=len(WORKSHOPS),
        timestamp=current_time(),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8750, debug=False)
