import json
from datetime import datetime, timezone
from wsgiref.simple_server import make_server

import yaml
from werkzeug.serving import run_simple
from werkzeug.wrappers import Request, Response


REPAIRS = {
    "binding": {
        "name": "Binding Repair",
        "bench": "Bench A",
        "estimated_minutes": 45,
    },
    "pages": {
        "name": "Page Mending",
        "bench": "Bench B",
        "estimated_minutes": 30,
    },
    "cover": {
        "name": "Cover Restoration",
        "bench": "Bench C",
        "estimated_minutes": 60,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(payload, status=200):
    return Response(
        json.dumps(payload),
        status=status,
        content_type="application/json; charset=utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def import_repair_ticket(document):
    if not isinstance(document, str) or not document.strip():
        return {"ok": False, "error": "Repair ticket is required."}

    if len(document) > 8192:
        return {"ok": False, "error": "Repair ticket is too large."}

    try:
        # CWE-502: a POST form field is parsed with Python object constructors.
        ticket = yaml.load(document, Loader=yaml.UnsafeLoader)
    except Exception:
        return {"ok": False, "error": "Repair ticket could not be decoded."}

    if not isinstance(ticket, dict):
        return {"ok": False, "error": "Repair ticket must contain a mapping."}

    repair_id = ticket.get("repair_id")
    librarian = ticket.get("librarian")
    book_title = ticket.get("book_title")

    if not isinstance(repair_id, str) or repair_id not in REPAIRS:
        return {"ok": False, "error": "Unknown repair type."}

    if not isinstance(librarian, str) or not librarian.strip():
        return {"ok": False, "error": "Librarian is required."}

    if not isinstance(book_title, str) or not book_title.strip():
        return {"ok": False, "error": "Book title is required."}

    return {
        "ok": True,
        "ticket": {
            "repair_id": repair_id,
            "librarian": librarian,
            "book_title": book_title,
            "imported_at": current_time(),
        },
    }


@Request.application
def application(request):
    request.max_content_length = 16384

    if request.path == "/" and request.method == "GET":
        return json_response(
            {
                "application": "Book Conservation Intake Desk",
                "repairs": "/repairs",
                "ticket_import": "/tickets/import",
                "selector": "URL-encoded POST form field ticket_yaml",
            }
        )

    if request.path == "/repairs" and request.method == "GET":
        return json_response(
            {
                "repairs": [
                    {"id": repair_id, **details}
                    for repair_id, details in REPAIRS.items()
                ]
            }
        )

    if request.path == "/health" and request.method == "GET":
        return json_response(
            {
                "status": "ok",
                "timestamp": current_time(),
                "repair_type_count": len(REPAIRS),
            }
        )

    if request.path == "/tickets/import" and request.method == "POST":
        document = request.form.get("ticket_yaml", "")
        result = import_repair_ticket(document)
        return json_response(result, status=201 if result["ok"] else 400)

    return json_response({"error": "Endpoint not found."}, status=404)


def main():
    run_simple(
        hostname="127.0.0.1",
        port=8470,
        application=application,
        use_debugger=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
