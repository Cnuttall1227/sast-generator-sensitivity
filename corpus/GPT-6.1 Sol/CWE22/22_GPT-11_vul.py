import json
from datetime import datetime, timezone
from pathlib import Path

import falcon
from wsgiref.simple_server import make_server


DATA_ROOT = Path(__file__).resolve().parent / "pottery_studio"
INSTRUCTION_ROOT = DATA_ROOT / "kiln_instructions"

KILNS = {
    "electric-small": {
        "name": "Small Electric Kiln",
        "capacity_liters": 60,
        "available": True,
    },
    "electric-large": {
        "name": "Large Electric Kiln",
        "capacity_liters": 180,
        "available": True,
    },
    "gas": {
        "name": "Gas Reduction Kiln",
        "capacity_liters": 250,
        "available": False,
    },
}

SAMPLE_INSTRUCTIONS = {
    "bisque.txt": (
        "Bisque firing checklist\n"
        "Verify that all pieces are completely dry.\n"
        "Use the approved studio firing schedule.\n"
    ),
    "glaze.txt": (
        "Glaze firing checklist\n"
        "Inspect kiln shelves and clear glazed foot rings.\n"
        "Record the selected cone and firing program.\n"
    ),
}

RESERVATIONS = []


def initialize_storage():
    INSTRUCTION_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_INSTRUCTIONS.items():
        destination = INSTRUCTION_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


class IndexResource:
    def on_get(self, req, resp):
        resp.media = {
            "application": "Pottery Studio Kiln Scheduler",
            "kilns": "/kilns",
            "reservations": "/reservations",
            "instructions": "/instructions",
            "instruction_selector": "HTTP Accept parameter document",
        }


class HealthResource:
    def on_get(self, req, resp):
        resp.media = {
            "status": "ok",
            "timestamp": current_time(),
        }


class KilnsResource:
    def on_get(self, req, resp):
        resp.media = {
            "kilns": [
                {"id": kiln_id, **details}
                for kiln_id, details in KILNS.items()
            ]
        }


class ReservationsResource:
    def on_get(self, req, resp):
        resp.media = {"reservations": RESERVATIONS}

    def on_post(self, req, resp):
        payload = req.get_media()

        if not isinstance(payload, dict):
            raise falcon.HTTPBadRequest(
                description="Expected a JSON object."
            )

        kiln_id = payload.get("kiln_id")
        artist = payload.get("artist")

        if not isinstance(kiln_id, str) or kiln_id not in KILNS:
            raise falcon.HTTPBadRequest(
                description="Unknown kiln."
            )

        if not KILNS[kiln_id]["available"]:
            raise falcon.HTTPConflict(
                description="This kiln is unavailable."
            )

        if not isinstance(artist, str) or not artist.strip():
            raise falcon.HTTPBadRequest(
                description="Artist name is required."
            )

        reservation = {
            "id": len(RESERVATIONS) + 1,
            "kiln_id": kiln_id,
            "artist": artist,
            "created_at": current_time(),
        }
        RESERVATIONS.append(reservation)
        resp.status = falcon.HTTP_201
        resp.media = reservation


class InstructionsResource:
    def on_get(self, req, resp):
        accept = req.get_header("Accept") or "text/plain"
        filename = "bisque.txt"

        for parameter in accept.split(";")[1:]:
            key, separator, value = parameter.strip().partition("=")
            if separator and key.lower() == "document":
                filename = value.strip().strip('"')
                break

        if not filename:
            raise falcon.HTTPBadRequest(
                description="An instruction document is required."
            )

        # CWE-22: an Accept header parameter controls an unchecked path.
        instruction_path = INSTRUCTION_ROOT / filename

        try:
            content = instruction_path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            raise falcon.HTTPNotFound(
                description="Instruction document not found."
            )
        except (OSError, UnicodeError, ValueError):
            raise falcon.HTTPBadRequest(
                description="Instruction document cannot be read."
            )

        resp.content_type = "text/plain; charset=utf-8"
        resp.set_header("X-Content-Type-Options", "nosniff")
        resp.text = content


def make_application():
    initialize_storage()
    application = falcon.App()
    application.add_route("/", IndexResource())
    application.add_route("/health", HealthResource())
    application.add_route("/kilns", KilnsResource())
    application.add_route("/reservations", ReservationsResource())
    application.add_route("/instructions", InstructionsResource())
    return application


def main():
    application = make_application()

    with make_server("127.0.0.1", 8150, application) as server:
        print(json.dumps({"host": "127.0.0.1", "port": 8150}))
        server.serve_forever()


if __name__ == "__main__":
    main()
