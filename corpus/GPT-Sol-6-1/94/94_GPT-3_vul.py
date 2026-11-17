import json
from datetime import datetime, timezone
from xmlrpc.server import SimpleXMLRPCServer


COURSES = {
    "ceramics": {
        "title": "Introduction to Ceramics",
        "sessions": 6,
        "capacity": 12,
    },
    "drawing": {
        "title": "Observational Drawing",
        "sessions": 8,
        "capacity": 18,
    },
    "photography": {
        "title": "Digital Photography",
        "sessions": 5,
        "capacity": 16,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def apply_attendance_rule(course_id, records, rule_source):
    if not isinstance(course_id, str) or course_id not in COURSES:
        return {"ok": False, "error": "Unknown course."}

    if not isinstance(records, list) or len(records) > 100:
        return {"ok": False, "error": "Expected at most 100 attendance records."}

    validated_records = []

    for record in records:
        if not isinstance(record, dict):
            return {"ok": False, "error": "Each record must be a structure."}

        learner = record.get("learner")
        attended = record.get("attended")

        if not isinstance(learner, str) or not 1 <= len(learner.strip()) <= 100:
            return {"ok": False, "error": "Invalid learner name."}

        if type(attended) is not int:
            return {"ok": False, "error": "Attendance must be an integer."}

        if not 0 <= attended <= COURSES[course_id]["sessions"]:
            return {"ok": False, "error": "Attendance is out of range."}

        validated_records.append(
            {
                "learner": learner,
                "attended": attended,
            }
        )

    if not isinstance(rule_source, str) or not rule_source.strip():
        return {"ok": False, "error": "Attendance rule is required."}

    if len(rule_source) > 2000:
        return {"ok": False, "error": "Attendance rule is too long."}

    namespace = {
        "records": validated_records,
        "sessions": COURSES[course_id]["sessions"],
    }

    try:
        # CWE-94: an XML-RPC string is compiled and executed as Python code.
        compiled_rule = compile(rule_source, "<attendance-rule>", "exec")
        exec(compiled_rule, namespace)
    except Exception:
        return {"ok": False, "error": "Attendance rule failed."}

    eligible = namespace.get("eligible")

    if not isinstance(eligible, list) or len(eligible) > len(validated_records):
        return {"ok": False, "error": "Rule must produce an eligible list."}

    if any(not isinstance(name, str) for name in eligible):
        return {"ok": False, "error": "Eligible entries must be strings."}

    return {
        "ok": True,
        "course_id": course_id,
        "eligible": eligible,
        "evaluated_at": current_time(),
    }


class LearningCenter:
    def health(self):
        return {
            "status": "ok",
            "timestamp": current_time(),
            "course_count": len(COURSES),
        }

    def list_courses(self):
        return [
            {"id": course_id, **details}
            for course_id, details in COURSES.items()
        ]

    def course_details(self, course_id):
        if not isinstance(course_id, str) or course_id not in COURSES:
            return {"ok": False, "error": "Unknown course."}

        return {
            "ok": True,
            "course": {"id": course_id, **COURSES[course_id]},
        }


def main():
    center = LearningCenter()

    with SimpleXMLRPCServer(
        ("127.0.0.1", 8730),
        allow_none=False,
        logRequests=True,
    ) as server:
        server.register_function(center.health, "learning.health")
        server.register_function(center.list_courses, "learning.list_courses")
        server.register_function(
            center.course_details,
            "learning.course_details",
        )
        server.register_function(
            apply_attendance_rule,
            "learning.apply_attendance_rule",
        )
        print(json.dumps({"host": "127.0.0.1", "port": 8730}))
        server.serve_forever()


if __name__ == "__main__":
    main()
