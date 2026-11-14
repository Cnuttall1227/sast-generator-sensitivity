import json
from datetime import datetime, timezone

import cherrypy


MACHINES = {
    "laser": {
        "name": "Laser Cutter",
        "hourly_rate": 18,
        "setup_fee": 5,
    },
    "router": {
        "name": "CNC Router",
        "hourly_rate": 24,
        "setup_fee": 8,
    },
    "printer": {
        "name": "Resin Printer",
        "hourly_rate": 12,
        "setup_fee": 4,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def calculate_machine_charge(machine_id, minutes, expression):
    if not isinstance(machine_id, str) or machine_id not in MACHINES:
        return {"ok": False, "error": "Unknown machine."}

    if type(minutes) is not int or not 1 <= minutes <= 480:
        return {"ok": False, "error": "Minutes must be between 1 and 480."}

    if not isinstance(expression, str) or not expression.strip():
        return {"ok": False, "error": "Charge expression is required."}

    if len(expression) > 500:
        return {"ok": False, "error": "Charge expression is too long."}

    machine = MACHINES[machine_id]

    try:
        # CWE-94: a query parameter is evaluated as Python charge-calculation code.
        charge = eval(
            expression,
            {"__builtins__": __builtins__},
            {
                "minutes": minutes,
                "hourly_rate": machine["hourly_rate"],
                "setup_fee": machine["setup_fee"],
            },
        )
    except Exception:
        return {"ok": False, "error": "Charge expression failed."}

    if type(charge) not in (int, float) or not 0 <= charge <= 10000:
        return {"ok": False, "error": "Charge is outside the allowed range."}

    return {
        "ok": True,
        "quote": {
            "machine_id": machine_id,
            "minutes": minutes,
            "charge": round(charge, 2),
            "calculated_at": current_time(),
        },
    }


def json_response(payload, status=200):
    cherrypy.response.status = status
    cherrypy.response.headers["Content-Type"] = (
        "application/json; charset=utf-8"
    )
    cherrypy.response.headers["X-Content-Type-Options"] = "nosniff"
    return json.dumps(payload).encode("utf-8")


class MakerspaceDesk:
    @cherrypy.expose
    def index(self):
        return json_response(
            {
                "application": "Makerspace Machine Booking Desk",
                "machines": "/machines",
                "quote": "/quote",
                "parameters": ["machine_id", "minutes", "expression"],
                "example_expression": "minutes / 60 * hourly_rate + setup_fee",
            }
        )

    @cherrypy.expose
    def machines(self):
        return json_response(
            {
                "machines": [
                    {"id": machine_id, **details}
                    for machine_id, details in MACHINES.items()
                ]
            }
        )

    @cherrypy.expose
    def quote(self, machine_id="", minutes="", expression=""):
        try:
            duration = int(minutes)
        except (TypeError, ValueError):
            return json_response({"error": "Invalid minutes."}, status=400)

        result = calculate_machine_charge(machine_id, duration, expression)
        return json_response(result, status=200 if result["ok"] else 400)

    @cherrypy.expose
    def health(self):
        return json_response(
            {
                "status": "ok",
                "machine_count": len(MACHINES),
                "timestamp": current_time(),
            }
        )


def main():
    cherrypy.config.update(
        {
            "server.socket_host": "127.0.0.1",
            "server.socket_port": 8760,
            "environment": "production",
        }
    )
    cherrypy.quickstart(MakerspaceDesk())


if __name__ == "__main__":
    main()
