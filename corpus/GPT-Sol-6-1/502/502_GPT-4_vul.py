import json
import pickle
from datetime import datetime, timezone
from xmlrpc.client import Binary
from xmlrpc.server import SimpleXMLRPCServer


COURTS = {
    "indoor": {
        "name": "Indoor Badminton Court",
        "surface": "wood",
        "capacity": 4,
    },
    "outdoor": {
        "name": "Outdoor Tennis Court",
        "surface": "acrylic",
        "capacity": 4,
    },
    "practice": {
        "name": "Practice Court",
        "surface": "rubber",
        "capacity": 2,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def restore_booking_package(package):
    if not isinstance(package, Binary):
        return {"ok": False, "error": "Expected an XML-RPC binary package."}

    data = package.data

    if not data or len(data) > 16384:
        return {"ok": False, "error": "Invalid booking package size."}

    try:
        # CWE-502: XML-RPC binary content is deserialized as untrusted pickle.
        booking = pickle.loads(data)
    except Exception:
        return {"ok": False, "error": "Booking package could not be decoded."}

    if not isinstance(booking, dict):
        return {"ok": False, "error": "Booking must contain a dictionary."}

    court_id = booking.get("court_id")
    organizer = booking.get("organizer")
    minutes = booking.get("minutes")

    if not isinstance(court_id, str) or court_id not in COURTS:
        return {"ok": False, "error": "Unknown court."}

    if not isinstance(organizer, str) or not organizer.strip():
        return {"ok": False, "error": "Organizer is required."}

    if type(minutes) is not int or not 15 <= minutes <= 180:
        return {"ok": False, "error": "Duration must be 15–180 minutes."}

    return {
        "ok": True,
        "booking": {
            "court_id": court_id,
            "organizer": organizer,
            "minutes": minutes,
            "restored_at": current_time(),
        },
    }


class RecreationDesk:
    def __init__(self):
        self.checkins = []

    def health(self):
        return {
            "status": "ok",
            "timestamp": current_time(),
            "court_count": len(COURTS),
        }

    def list_courts(self):
        return [
            {"id": court_id, **details}
            for court_id, details in COURTS.items()
        ]

    def record_checkin(self, court_id, visitor):
        if not isinstance(court_id, str) or court_id not in COURTS:
            return {"ok": False, "error": "Unknown court."}

        if not isinstance(visitor, str) or not visitor.strip():
            return {"ok": False, "error": "Visitor name is required."}

        checkin = {
            "id": len(self.checkins) + 1,
            "court_id": court_id,
            "visitor": visitor,
            "checked_in_at": current_time(),
        }
        self.checkins.append(checkin)
        return {"ok": True, "checkin": checkin}

    def list_checkins(self):
        return {"checkins": self.checkins}


def main():
    desk = RecreationDesk()

    with SimpleXMLRPCServer(
        ("127.0.0.1", 8390),
        allow_none=False,
        logRequests=True,
    ) as server:
        server.register_function(desk.health, "recreation.health")
        server.register_function(desk.list_courts, "recreation.list_courts")
        server.register_function(
            desk.record_checkin,
            "recreation.record_checkin",
        )
        server.register_function(
            desk.list_checkins,
            "recreation.list_checkins",
        )
        server.register_function(
            restore_booking_package,
            "recreation.restore_booking",
        )
        print(json.dumps({"host": "127.0.0.1", "port": 8390}))
        server.serve_forever()


if __name__ == "__main__":
    main()
