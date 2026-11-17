import json
import subprocess
from datetime import datetime, timezone

import cherrypy


PLOTS = {
    "north": {
        "name": "North Orchard",
        "trees": 36,
        "crop": "apples",
    },
    "south": {
        "name": "South Orchard",
        "trees": 24,
        "crop": "pears",
    },
    "west": {
        "name": "West Orchard",
        "trees": 18,
        "crop": "plums",
    },
}

HARVESTS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def inspect_sensor_service(service_name):
    import re

    if not isinstance(service_name, str) or not service_name.strip():
        return {"ok": False, "error": "Sensor service name is required."}

    service_name = service_name.strip()

    if len(service_name) > 160:
        return {"ok": False, "error": "Sensor service name is too long."}

    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:-]*", service_name):
        return {"ok": False, "error": "Invalid sensor service name."}

    try:
        result = subprocess.run(
            ["systemctl", "--no-pager", "status", "--", service_name],
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Sensor service inspection timed out."}
    except OSError:
        return {"ok": False, "error": "Sensor service inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "service": service_name,
        "output": result.stdout[:4000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


def json_response(payload, status=200):
    cherrypy.response.status = status
    cherrypy.response.headers["Content-Type"] = (
        "application/json; charset=utf-8"
    )
    cherrypy.response.headers["X-Content-Type-Options"] = "nosniff"
    return json.dumps(payload).encode("utf-8")


class OrchardDesk:
    @cherrypy.expose
    def index(self):
        return json_response(
            {
                "application": "Orchard Sensor and Harvest Desk",
                "plots": "/plots",
                "harvests": "/harvests",
                "sensor_check": "/sensor_check",
                "selector": 'X-Sensor-Selection: {"service": "orchard-sensor"}',
            }
        )

    @cherrypy.expose
    def plots(self):
        return json_response(
            {
                "plots": [
                    {"id": plot_id, **details}
                    for plot_id, details in PLOTS.items()
                ]
            }
        )

    @cherrypy.expose
    def harvests(self):
        return json_response({"harvests": HARVESTS})

    @cherrypy.expose
    def record_harvest(self, plot_id="", kilograms=""):
        if cherrypy.request.method != "POST":
            return json_response({"error": "Use POST."}, status=405)

        if plot_id not in PLOTS:
            return json_response({"error": "Unknown plot."}, status=400)

        try:
            weight = float(kilograms)
        except ValueError:
            return json_response({"error": "Invalid weight."}, status=400)

        if not 0 < weight <= 10000:
            return json_response({"error": "Weight is out of range."}, status=400)

        harvest = {
            "id": len(HARVESTS) + 1,
            "plot_id": plot_id,
            "kilograms": weight,
            "recorded_at": current_time(),
        }
        HARVESTS.append(harvest)
        return json_response(harvest, status=201)

    @cherrypy.expose
    def sensor_check(self):
        raw_selection = cherrypy.request.headers.get(
            "X-Sensor-Selection",
            '{"service": "orchard-sensor"}',
        )

        try:
            selection = json.loads(raw_selection)
        except (ValueError, UnicodeError):
            return json_response({"error": "Invalid selection JSON."}, status=400)

        if not isinstance(selection, dict):
            return json_response({"error": "Expected an object."}, status=400)

        return json_response(
            inspect_sensor_service(selection.get("service"))
        )


def main():
    cherrypy.config.update(
        {
            "server.socket_host": "127.0.0.1",
            "server.socket_port": 8300,
            "environment": "production",
        }
    )
    cherrypy.quickstart(OrchardDesk())


if __name__ == "__main__":
    main()
