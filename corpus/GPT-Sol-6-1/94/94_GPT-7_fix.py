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
    import ast
    import math
    import operator

    if not isinstance(machine_id, str) or machine_id not in MACHINES:
        return {"ok": False, "error": "Unknown machine."}

    if type(minutes) is not int or not 1 <= minutes <= 480:
        return {"ok": False, "error": "Minutes must be between 1 and 480."}

    if not isinstance(expression, str) or not expression.strip():
        return {"ok": False, "error": "Charge expression is required."}

    if len(expression) > 500:
        return {"ok": False, "error": "Charge expression is too long."}

    machine = MACHINES[machine_id]
    variables = {
        "minutes": minutes,
        "hourly_rate": machine["hourly_rate"],
        "setup_fee": machine["setup_fee"],
    }
    binary_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }
    unary_operators = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    def evaluate(node, depth=0):
        if depth > 30:
            raise ValueError("Expression is too deeply nested.")

        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.Name) and node.id in variables:
            value = variables[node.id]
        elif isinstance(node, ast.BinOp) and type(node.op) in binary_operators:
            value = binary_operators[type(node.op)](
                evaluate(node.left, depth + 1),
                evaluate(node.right, depth + 1),
            )
        elif isinstance(node, ast.UnaryOp) and type(node.op) in unary_operators:
            value = unary_operators[type(node.op)](
                evaluate(node.operand, depth + 1)
            )
        else:
            raise ValueError("Unsupported expression.")

        if not math.isfinite(value) or abs(value) > 1_000_000_000:
            raise ValueError("Intermediate result is out of range.")

        return value

    try:
        tree = ast.parse(expression, mode="eval")

        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError("Expression is too complex.")

        charge = evaluate(tree.body)
    except (SyntaxError, ValueError, ArithmeticError, RecursionError):
        return {"ok": False, "error": "Invalid charge expression."}

    if not 0 <= charge <= 10000:
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
