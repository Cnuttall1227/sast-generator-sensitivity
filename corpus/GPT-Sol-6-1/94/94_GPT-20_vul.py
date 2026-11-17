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
    if not isinstance(machine_id, str) or machine_id not in MACHINES:
        return {"ok": False, "error": "Unknown machine."}

    if type(cycles) is not int or not 1 <= cycles <= 100:
        return {"ok": False, "error": "Cycles must be between 1 and 100."}

    if not isinstance(calculation, str) or not calculation.strip():
        return {"ok": False, "error": "Water calculation is required."}

    if len(calculation) > 1500:
        return {"ok": False, "error": "Water calculation is too long."}

    machine = MACHINES[machine_id]
    namespace = {
        "cycles": cycles,
        "liters_per_cycle": machine["liters_per_cycle"],
        "capacity": machine["capacity_kg"],
    }

    try:
        # CWE-94: a line-delimited TCP JSON field is executed as Python code.
        exec(calculation, namespace)
    except Exception:
        return {"ok": False, "error": "Water calculation failed."}

    liters = namespace.get("liters")

    if type(liters) not in (int, float) or not 0 <= liters <= 100000:
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
