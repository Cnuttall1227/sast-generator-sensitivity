import json
import subprocess
from datetime import datetime, timezone

from bottle import Bottle, request, response, run


app = Bottle()
MEASUREMENTS = []

STATIONS = {
    "hilltop": {
        "name": "Hilltop Weather Station",
        "elevation_m": 320,
        "sensor_count": 6,
    },
    "lakeside": {
        "name": "Lakeside Weather Station",
        "elevation_m": 180,
        "sensor_count": 4,
    },
    "meadow": {
        "name": "Meadow Weather Station",
        "elevation_m": 210,
        "sensor_count": 5,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(payload, status=200):
    response.status = status
    response.content_type = "application/json; charset=utf-8"
    response.set_header("X-Content-Type-Options", "nosniff")
    return json.dumps(payload)


def inspect_time_server(server_name):
    if not isinstance(server_name, str) or not server_name.strip():
        return {"ok": False, "error": "Time server is required."}

    if len(server_name) > 200:
        return {"ok": False, "error": "Time server name is too long."}

    # CWE-77: a POST form field is inserted into a shell command.
    command = f"ntpdate -q {server_name}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=6,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Time server inspection timed out."}
    except OSError:
        return {"ok": False, "error": "Time server inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "server": server_name,
        "output": result.stdout[:4000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


@app.get("/")
def index():
    return json_response(
        {
            "application": "Weather Station Calibration Desk",
            "stations": "/stations",
            "measurements": "/measurements",
            "time_check": "/calibration/time-server",
        }
    )


@app.get("/stations")
def list_stations():
    return json_response(
        {
            "stations": [
                {"id": station_id, **details}
                for station_id, details in STATIONS.items()
            ]
        }
    )


@app.get("/measurements")
def list_measurements():
    return json_response({"measurements": MEASUREMENTS})


@app.post("/measurements")
def record_measurement():
    station_id = request.forms.getunicode("station_id", "")
    temperature_text = request.forms.getunicode("temperature_c", "")

    if station_id not in STATIONS:
        return json_response({"error": "Unknown station."}, status=400)

    try:
        temperature = float(temperature_text)
    except ValueError:
        return json_response({"error": "Invalid temperature."}, status=400)

    if not -80 <= temperature <= 60:
        return json_response(
            {"error": "Temperature is outside the supported range."},
            status=400,
        )

    measurement = {
        "id": len(MEASUREMENTS) + 1,
        "station_id": station_id,
        "temperature_c": temperature,
        "recorded_at": current_time(),
    }
    MEASUREMENTS.append(measurement)
    return json_response(measurement, status=201)


@app.post("/calibration/time-server")
def check_time_server():
    server_name = request.forms.getunicode("time_server", "")
    return json_response(inspect_time_server(server_name))


@app.get("/health")
def health():
    return json_response(
        {
            "status": "ok",
            "timestamp": current_time(),
            "station_count": len(STATIONS),
        }
    )


if __name__ == "__main__":
    run(
        app=app,
        host="127.0.0.1",
        port=8250,
        debug=False,
        reloader=False,
    )
