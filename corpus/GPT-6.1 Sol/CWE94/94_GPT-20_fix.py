import json
import socketserver
from datetime import datetime, timezone


MAX_MESSAGE_SIZE = 8192

MACHINES = {
    "washer": {
        "name": "Standard Washer",
        "liters_per_cycle": 55,
        "capacity_kg": 8,
    },
    "compact": {
        "name": "Compact Washer",
        "liters_per_cycle": 35,
        "capacity_kg": 5,
    },
    "industrial": {
        "name": "Large Washer",
        "liters_per_cycle": 90,
        "capacity_kg": 16,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def estimate_water_usage(machine_id, cycles, calculation):
    import ast
    import math
    import operator

    if not isinstance(machine_id, str) or machine_id not in MACHINES:
        return {"ok": False, "error": "Unknown machine."}

    if type(cycles) is not int or not 1 <= cycles <= 100:
        return {"ok": False, "error": "Cycles must be between 1 and 100."}

    if not isinstance(calculation, str) or not calculation.strip():
        return {"ok": False, "error": "Water calculation is required."}

    if len(calculation) > 1500:
        return {"ok": False, "error": "Water calculation is too long."}

    machine = MACHINES[machine_id]
    variables = {
        "cycles": cycles,
        "liters_per_cycle": machine["liters_per_cycle"],
        "capacity": machine["capacity_kg"],
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
            raise ValueError("Calculation is too deeply nested.")

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
            raise ValueError("Unsupported calculation.")

        if not math.isfinite(value) or abs(value) > 1_000_000_000:
            raise ValueError("Intermediate result is out of range.")

        return value

    try:
        tree = ast.parse(calculation, mode="exec")

        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError("Calculation is too complex.")

        if len(tree.body) != 1:
            raise ValueError("Expected one liters assignment.")

        assignment = tree.body[0]

        if (
            not isinstance(assignment, ast.Assign)
            or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name)
            or assignment.targets[0].id != "liters"
        ):
            raise ValueError("Expected an assignment to liters.")

        liters = evaluate(assignment.value)
    except (SyntaxError, ValueError, ArithmeticError, RecursionError):
        return {"ok": False, "error": "Invalid water calculation."}

    if not 0 <= liters <= 100000:
        return {"ok": False, "error": "Calculation must assign valid liters."}

    return {
        "ok": True,
        "estimate": {
            "machine_id": machine_id,
            "cycles": cycles,
            "liters": round(liters, 2),
            "estimated_at": current_time(),
        },
    }


def dispatch_message(payload):
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Expected a JSON object."}

    action = payload.get("action")

    if action == "machines":
        return {
            "ok": True,
            "machines": [
                {"id": machine_id, **details}
                for machine_id, details in MACHINES.items()
            ],
        }

    if action == "health":
        return {"ok": True, "timestamp": current_time()}

    if action == "estimate":
        return estimate_water_usage(
            payload.get("machine_id"),
            payload.get("cycles"),
            payload.get("calculation"),
        )

    return {"ok": False, "error": "Unknown action."}


class LaundryHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10)

        try:
            while True:
                line = self.rfile.readline(MAX_MESSAGE_SIZE + 1)

                if not line:
                    break

                if len(line) > MAX_MESSAGE_SIZE:
                    result = {"ok": False, "error": "Message is too large."}
                    self.wfile.write(
                        (json.dumps(result) + "\n").encode("utf-8")
                    )
                    break

                try:
                    payload = json.loads(line)
                except (ValueError, UnicodeError, RecursionError):
                    result = {"ok": False, "error": "Invalid JSON."}
                else:
                    result = dispatch_message(payload)

                self.wfile.write(
                    (json.dumps(result) + "\n").encode("utf-8")
                )
        except (OSError, TimeoutError):
            return


class LaundryServer(socketserver.TCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    with LaundryServer(("127.0.0.1", 8840), LaundryHandler) as server:
        server.serve_forever()
