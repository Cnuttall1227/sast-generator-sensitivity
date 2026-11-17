import json
from datetime import datetime, timezone

import tornado.ioloop
import tornado.web


STATIONS = {
    "north": {
        "name": "North Stream Station",
        "baseline": 12.0,
        "unit": "centimeters",
    },
    "east": {
        "name": "East Stream Station",
        "baseline": 8.5,
        "unit": "centimeters",
    },
    "south": {
        "name": "South Stream Station",
        "baseline": 15.0,
        "unit": "centimeters",
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def calibrate_reading(station_id, reading, formula):
    if not isinstance(station_id, str) or station_id not in STATIONS:
        return {"ok": False, "error": "Unknown station."}

    if type(reading) not in (int, float) or not -1000 <= reading <= 1000:
        return {"ok": False, "error": "Reading is outside the allowed range."}

    if not isinstance(formula, str) or not formula.strip():
        return {"ok": False, "error": "Calibration formula is required."}

    if len(formula) > 500:
        return {"ok": False, "error": "Calibration formula is too long."}

    baseline = STATIONS[station_id]["baseline"]

    try:
        # CWE-94: a browser cookie is evaluated as a Python expression.
        adjusted = eval(
            formula,
            {"__builtins__": __builtins__},
            {"reading": reading, "baseline": baseline},
        )
    except Exception:
        return {"ok": False, "error": "Calibration formula failed."}

    if type(adjusted) not in (int, float) or not -10000 <= adjusted <= 10000:
        return {"ok": False, "error": "Adjusted reading is out of range."}

    return {
        "ok": True,
        "calibration": {
            "station_id": station_id,
            "reading": reading,
            "adjusted": round(adjusted, 3),
            "unit": STATIONS[station_id]["unit"],
            "calibrated_at": current_time(),
        },
    }


class BaseHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("X-Content-Type-Options", "nosniff")

    def write_json(self, payload, status=200):
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.finish(json.dumps(payload))


class IndexHandler(BaseHandler):
    def get(self):
        self.write_json(
            {
                "application": "Community Stream Monitoring Desk",
                "stations": "/stations",
                "calibrate": "/readings/calibrate",
                "formula_cookie": "stream_calibration",
                "example_formula": "reading - baseline",
            }
        )


class StationsHandler(BaseHandler):
    def get(self):
        self.write_json(
            {
                "stations": [
                    {"id": station_id, **details}
                    for station_id, details in STATIONS.items()
                ]
            }
        )


class CalibrationHandler(BaseHandler):
    def post(self):
        try:
            payload = json.loads(self.request.body)
        except (ValueError, UnicodeError, RecursionError):
            self.write_json({"error": "Expected valid JSON."}, status=400)
            return

        if not isinstance(payload, dict):
            self.write_json({"error": "Expected an object."}, status=400)
            return

        formula = self.get_cookie(
            "stream_calibration",
            default="reading - baseline",
        )
        result = calibrate_reading(
            payload.get("station_id"),
            payload.get("reading"),
            formula,
        )
        self.write_json(result, status=200 if result["ok"] else 400)


class HealthHandler(BaseHandler):
    def get(self):
        self.write_json(
            {
                "status": "ok",
                "station_count": len(STATIONS),
                "timestamp": current_time(),
            }
        )


def main():
    application = tornado.web.Application(
        [
            (r"/", IndexHandler),
            (r"/stations", StationsHandler),
            (r"/readings/calibrate", CalibrationHandler),
            (r"/health", HealthHandler),
        ],
        debug=False,
    )
    application.listen(8770, address="127.0.0.1")
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
