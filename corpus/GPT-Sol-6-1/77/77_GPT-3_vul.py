import json
import subprocess
from datetime import datetime, timezone

from flask import Flask, jsonify, request


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8192

GARDENS = {
    "north": {
        "name": "North Community Garden",
        "plots": 24,
        "coordinator": "Alex",
    },
    "south": {
        "name": "South Community Garden",
        "plots": 18,
        "coordinator": "Morgan",
    },
    "east": {
        "name": "East Community Garden",
        "plots": 32,
        "coordinator": "Jamie",
    },
}

DELIVERIES = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def lookup_supplier_domain(domain):
    if not isinstance(domain, str) or not domain.strip():
        return {"ok": False, "error": "Supplier domain is required."}

    if len(domain) > 200:
        return {"ok": False, "error": "Supplier domain is too long."}

    # CWE-77: a query-string value is interpolated into a shell command.
    command = f"nslookup {domain}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Supplier lookup timed out."}
    except OSError:
        return {"ok": False, "error": "Supplier lookup could not start."}

    return {
        "ok": result.returncode == 0,
        "domain": domain,
        "output": result.stdout[:4000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


@app.get("/")
def index():
    return jsonify(
        application="Community Garden Delivery Desk",
        gardens="/gardens",
        deliveries="/deliveries",
        supplier_lookup="/suppliers/lookup?domain=example.org",
    )


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        timestamp=current_time(),
        garden_count=len(GARDENS),
    )


@app.get("/gardens")
def list_gardens():
    return jsonify(
        gardens=[
            {"id": garden_id, **details}
            for garden_id, details in GARDENS.items()
        ]
    )


@app.get("/deliveries")
def list_deliveries():
    return jsonify(deliveries=DELIVERIES)


@app.post("/deliveries")
def create_delivery():
    try:
        payload = json.loads(request.get_data())
    except (ValueError, UnicodeError):
        return jsonify(error="Invalid JSON."), 400

    if not isinstance(payload, dict):
        return jsonify(error="Expected a JSON object."), 400

    garden_id = payload.get("garden_id")
    supplies = payload.get("supplies")

    if not isinstance(garden_id, str) or garden_id not in GARDENS:
        return jsonify(error="Unknown garden."), 400

    if not isinstance(supplies, str) or not supplies.strip():
        return jsonify(error="Supplies description is required."), 400

    delivery = {
        "id": len(DELIVERIES) + 1,
        "garden_id": garden_id,
        "supplies": supplies,
        "created_at": current_time(),
    }
    DELIVERIES.append(delivery)
    return jsonify(delivery), 201


@app.get("/suppliers/lookup")
def supplier_lookup():
    domain = request.args.get("domain", "")
    result = lookup_supplier_domain(domain)
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8230, debug=False)
