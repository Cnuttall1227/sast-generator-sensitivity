import json
import pickle
import socketserver
from datetime import datetime, timezone


MAX_PACKET_SIZE = 8192

COURSES = {
    "navigation": {
        "title": "Map and Compass Navigation",
        "instructor": "Alex",
        "capacity": 12,
    },
    "shelter": {
        "title": "Outdoor Shelter Skills",
        "instructor": "Morgan",
        "capacity": 10,
    },
    "first-aid": {
        "title": "Wilderness First Aid",
        "instructor": "Jamie",
        "capacity": 16,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def import_assessment_packet(packet):
    if not isinstance(packet, bytes) or not packet:
        return {"ok": False, "error": "Assessment packet is required."}

    if len(packet) > MAX_PACKET_SIZE:
        return {"ok": False, "error": "Assessment packet is too large."}

    try:
        # CWE-502: an incoming UDP datagram is treated as a Python pickle.
        assessment = pickle.loads(packet)
    except Exception:
        return {"ok": False, "error": "Assessment packet could not be decoded."}

    if not isinstance(assessment, dict):
        return {"ok": False, "error": "Assessment must contain a dictionary."}

    course_id = assessment.get("course_id")
    learner = assessment.get("learner")
    score = assessment.get("score")

    if not isinstance(course_id, str) or course_id not in COURSES:
        return {"ok": False, "error": "Unknown course."}

    if not isinstance(learner, str) or not learner.strip():
        return {"ok": False, "error": "Learner name is required."}

    if type(score) is not int or not 0 <= score <= 100:
        return {"ok": False, "error": "Score must be an integer from 0 to 100."}

    return {
        "ok": True,
        "assessment": {
            "course_id": course_id,
            "learner": learner,
            "score": score,
            "imported_at": current_time(),
        },
    }


def dispatch_packet(packet):
    if packet == b"COURSES":
        return {
            "ok": True,
            "courses": [
                {"id": course_id, **details}
                for course_id, details in COURSES.items()
            ],
        }

    if packet == b"HEALTH":
        return {"ok": True, "timestamp": current_time()}

    return import_assessment_packet(packet)


class AssessmentHandler(socketserver.BaseRequestHandler):
    def handle(self):
        packet, transport = self.request
        result = dispatch_packet(packet)
        encoded = json.dumps(result).encode("utf-8")
        transport.sendto(encoded, self.client_address)


class AssessmentServer(socketserver.UDPServer):
    max_packet_size = MAX_PACKET_SIZE + 1


def main():
    with AssessmentServer(
        ("127.0.0.1", 8440),
        AssessmentHandler,
    ) as server:
        print("Outdoor skills assessment desk listening on 127.0.0.1:8440")
        server.serve_forever()


if __name__ == "__main__":
    main()
