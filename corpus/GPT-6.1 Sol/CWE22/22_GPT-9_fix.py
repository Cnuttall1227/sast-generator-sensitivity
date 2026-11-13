import json
from datetime import datetime, timezone
from pathlib import Path

import cherrypy


DATA_ROOT = Path(__file__).resolve().parent / "seed_library"
GUIDE_ROOT = DATA_ROOT / "growing_guides"

SEEDS = {
    "tomato": {
        "name": "Garden Tomato",
        "sunlight": "full sun",
        "days_to_germination": 7,
    },
    "basil": {
        "name": "Sweet Basil",
        "sunlight": "full sun",
        "days_to_germination": 10,
    },
    "lettuce": {
        "name": "Leaf Lettuce",
        "sunlight": "partial sun",
        "days_to_germination": 5,
    },
}

SAMPLE_GUIDES = {
    "tomato.txt": (
        "Garden Tomato\n"
        "Start indoors before the final frost.\n"
        "Transplant after nighttime temperatures rise.\n"
    ),
    "basil.txt": (
        "Sweet Basil\n"
        "Sow shallowly in moist soil.\n"
        "Harvest leaves regularly to encourage growth.\n"
    ),
    "lettuce.txt": (
        "Leaf Lettuce\n"
        "Sow in cool weather and water consistently.\n"
        "Provide afternoon shade during hot periods.\n"
    ),
}


def initialize_storage():
    GUIDE_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_GUIDES.items():
        destination = GUIDE_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(payload, status=200):
    cherrypy.response.status = status
    cherrypy.response.headers["Content-Type"] = (
        "application/json; charset=utf-8"
    )
    return json.dumps(payload).encode("utf-8")


class SeedLibrary:
    def __init__(self):
        self.loans = []

    @cherrypy.expose
    def index(self):
        return json_response(
            {
                "application": "Community Seed Lending Library",
                "catalog": "/catalog",
                "loans": "/loans",
                "guide": "/guide/<document path>",
            }
        )

    @cherrypy.expose
    def health(self):
        return json_response(
            {
                "status": "ok",
                "timestamp": current_time(),
            }
        )

    @cherrypy.expose
    def catalog(self):
        return json_response(
            {
                "seeds": [
                    {"id": seed_id, **details}
                    for seed_id, details in SEEDS.items()
                ]
            }
        )

    @cherrypy.expose
    def borrow(self, seed_id="", gardener=""):
        if cherrypy.request.method != "POST":
            return json_response(
                {"error": "Use POST to borrow seeds."},
                status=405,
            )

        if seed_id not in SEEDS:
            return json_response(
                {"error": "Unknown seed variety."},
                status=400,
            )

        if not gardener.strip():
            return json_response(
                {"error": "Gardener name is required."},
                status=400,
            )

        loan = {
            "id": len(self.loans) + 1,
            "seed_id": seed_id,
            "gardener": gardener,
            "created_at": current_time(),
        }
        self.loans.append(loan)
        return json_response(loan, status=201)

    @cherrypy.expose
    def loans(self):
        return json_response({"loans": self.loans})

    @cherrypy.expose
    def guide(self, *segments):
        if not segments:
            return json_response(
                {"error": "A guide document path is required."},
                status=400,
            )

        try:
            guide_directory = GUIDE_ROOT.resolve(strict=True)

            if any(Path(segment).is_absolute() for segment in segments):
                return json_response(
                    {"error": "Invalid guide path."},
                    status=400,
                )

            document_path = guide_directory.joinpath(*segments).resolve(
                strict=True
            )

            if not document_path.is_relative_to(guide_directory):
                return json_response(
                    {"error": "Invalid guide path."},
                    status=400,
                )

            content = document_path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            return json_response(
                {"error": "Growing guide not found."},
                status=404,
            )
        except (OSError, UnicodeError, ValueError, RuntimeError):
            return json_response(
                {"error": "Growing guide cannot be read."},
                status=400,
            )

        cherrypy.response.headers["Content-Type"] = (
            "text/plain; charset=utf-8"
        )
        cherrypy.response.headers["X-Content-Type-Options"] = "nosniff"
        return content.encode("utf-8")


def main():
    initialize_storage()
    cherrypy.config.update(
        {
            "server.socket_host": "127.0.0.1",
            "server.socket_port": 8130,
            "environment": "production",
        }
    )
    cherrypy.quickstart(SeedLibrary())


if __name__ == "__main__":
    main()
