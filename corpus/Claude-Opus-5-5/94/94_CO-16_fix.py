import os
import json
import logging
from datetime import datetime, timezone
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

LISTEN_HOST = os.environ.get("THERMO_RPC_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("THERMO_RPC_PORT", "8740"))
STATE_FILE = os.environ.get("THERMO_STATE", "/var/lib/thermostat/state.json")
MIN_SETPOINT = 10.0
MAX_SETPOINT = 30.0
MODES = ("off", "heat", "cool", "auto")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("thermostat-rpc")


class Schedule:
    def __init__(self, entries=None):
        self.entries = entries or {}

    def list(self):
        return [{"time": t, "setpoint": s} for t, s in sorted(self.entries.items())]

    def set(self, time_of_day, setpoint):
        hour, _, minute = str(time_of_day).partition(":")
        if not (hour.isdigit() and minute.isdigit() and 0 <= int(hour) < 24 and 0 <= int(minute) < 60):
            raise ValueError("time must look like HH:MM")
        setpoint = float(setpoint)
        if not MIN_SETPOINT <= setpoint <= MAX_SETPOINT:
            raise ValueError(f"setpoint must be {MIN_SETPOINT}-{MAX_SETPOINT} °C")
        self.entries[f"{int(hour):02d}:{int(minute):02d}"] = setpoint
        return True

    def clear(self, time_of_day):
        return self.entries.pop(str(time_of_day), None) is not None


class Thermostat:
    def __init__(self):
        self.mode = "auto"
        self.setpoint = 20.0
        self.current_temperature = 19.5
        self.schedule = Schedule()
        self.load()

    def load(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        self.mode = data.get("mode", self.mode)
        self.setpoint = float(data.get("setpoint", self.setpoint))
        self.schedule = Schedule(data.get("schedule", {}))

    def save(self):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as handle:
            json.dump({"mode": self.mode, "setpoint": self.setpoint, "schedule": self.schedule.entries}, handle)

    def status(self):
        return {
            "mode": self.mode,
            "setpoint": self.setpoint,
            "current": self.current_temperature,
            "heating": self.mode in ("heat", "auto") and self.current_temperature < self.setpoint - 0.3,
            "cooling": self.mode in ("cool", "auto") and self.current_temperature > self.setpoint + 0.3,
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        self.mode = mode
        self.save()
        log.info("Mode set to %s", mode)
        return self.status()

    def set_setpoint(self, value):
        value = float(value)
        if not MIN_SETPOINT <= value <= MAX_SETPOINT:
            raise ValueError(f"setpoint must be {MIN_SETPOINT}-{MAX_SETPOINT} °C")
        self.setpoint = round(value, 1)
        self.save()
        log.info("Setpoint set to %.1f", self.setpoint)
        return self.status()

    def set_schedule(self, time_of_day, setpoint):
        result = self.schedule.set(time_of_day, setpoint)
        self.save()
        return result

    def get_schedule(self):
        return self.schedule.list()


class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ("/RPC2",)


def build_server(thermostat):
    server = SimpleXMLRPCServer(
        (LISTEN_HOST, LISTEN_PORT),
        requestHandler=RequestHandler,
        allow_none=True,
        logRequests=False,
    )
    server.register_introspection_functions()

    def clear_schedule(time_of_day):
        removed = thermostat.schedule.clear(time_of_day)
        if removed:
            thermostat.save()
        return removed

    server.register_function(thermostat.status, "status")
    server.register_function(thermostat.set_mode, "set_mode")
    server.register_function(thermostat.set_setpoint, "set_setpoint")
    server.register_function(thermostat.set_schedule, "set_schedule")
    server.register_function(thermostat.get_schedule, "get_schedule")
    server.register_function(clear_schedule, "clear_schedule")
    return server

if __name__ == "__main__":
    device = Thermostat()
    server = build_server(device)
    log.info("Thermostat XML-RPC on %s:%d (mode %s, setpoint %.1f)", LISTEN_HOST, LISTEN_PORT, device.mode, device.setpoint)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Stopping")