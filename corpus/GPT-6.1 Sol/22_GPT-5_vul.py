import json
from datetime import datetime, timezone
from pathlib import Path
from xmlrpc.server import SimpleXMLRPCServer


DATA_ROOT = Path(__file__).resolve().parent / "costume_workshop"
PATTERN_ROOT = DATA_ROOT / "patterns"

PRODUCTIONS = {
    "winter-tale": {
        "title": "The Winter Tale",
        "designer": "Jordan",
        "costume_count": 18,
    },
    "city-lights": {
        "title": "City Lights",
        "designer": "Casey",
        "costume_count": 12,
    },
    "ocean-song": {
        "title": "Ocean Song",
        "designer": "Sam",
        "costume_count": 24,
    },
}

SAMPLE_PATTERNS = {
    "winter-tale": (
        "Winter cloak construction notes\n"
        "Material: blue wool\n"
        "Seam allowance: 15 mm\n"
    ),
    "city-lights": (
        "Evening jacket construction notes\n"
        "Material: black cotton\n"
        "Seam allowance: 10 mm\n"
    ),
    "ocean-song": (
        "Sailor tunic construction notes\n"
        "Material: white linen\n"
        "Seam allowance: 12 mm\n"
    ),
}


def initialize_storage():
    PATTERN_ROOT.mkdir(parents=True, exist_ok=True)

    for production_id, content in SAMPLE_PATTERNS.items():
        directory = PATTERN_ROOT / production_id
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / "instructions.txt"

        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


class CostumeWorkshopService:
    def __init__(self):
        self.fittings = []

    def health(self):
        return {
            "status": "ok",
            "timestamp": current_time(),
            "production_count": len(PRODUCTIONS),
        }

    def list_productions(self):
        return [
            {"id": production_id, **details}
            for production_id, details in PRODUCTIONS.items()
        ]

    def production_details(self, production_id):
        production = PRODUCTIONS.get(production_id)

        if production is None:
            return {"error": "Unknown production."}

        return {"id": production_id, **production}

    def schedule_fitting(self, production_id, performer, appointment):
        if production_id not in PRODUCTIONS:
            return {"error": "Unknown production."}

        if not all(
            isinstance(value, str) and value.strip()
            for value in (performer, appointment)
        ):
            return {"error": "Performer and appointment are required."}

        fitting = {
            "id": len(self.fittings) + 1,
            "production_id": production_id,
            "performer": performer,
            "appointment": appointment,
            "created_at": current_time(),
        }
        self.fittings.append(fitting)
        return fitting

    def list_fittings(self, production_id):
        if production_id not in PRODUCTIONS:
            return {"error": "Unknown production."}

        return [
            fitting
            for fitting in self.fittings
            if fitting["production_id"] == production_id
        ]

    def read_pattern(self, production_id, options):
        if production_id not in PRODUCTIONS:
            return {"error": "Unknown production."}

        if not isinstance(options, dict):
            return {"error": "Options must be a structure."}

        filename = options.get("document", "instructions.txt")

        if not isinstance(filename, str):
            return {"error": "Document must be a string."}

        # CWE-22: an XML-RPC structure supplies an unchecked document path.
        document_path = PATTERN_ROOT / production_id / filename

        try:
            content = document_path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            return {"error": "Pattern document not found."}
        except (OSError, UnicodeError, ValueError):
            return {"error": "Pattern document cannot be read."}

        return {
            "production_id": production_id,
            "document": filename,
            "content": content,
        }


def main():
    initialize_storage()
    service = CostumeWorkshopService()

    with SimpleXMLRPCServer(
        ("127.0.0.1", 8090),
        allow_none=False,
        logRequests=True,
    ) as server:
        server.register_function(service.health, "workshop.health")
        server.register_function(
            service.list_productions,
            "workshop.list_productions",
        )
        server.register_function(
            service.production_details,
            "workshop.production_details",
        )
        server.register_function(
            service.schedule_fitting,
            "workshop.schedule_fitting",
        )
        server.register_function(
            service.list_fittings,
            "workshop.list_fittings",
        )
        server.register_function(
            service.read_pattern,
            "workshop.read_pattern",
        )
        print(json.dumps({"address": "127.0.0.1", "port": 8090}))
        server.serve_forever()


if __name__ == "__main__":
    main()
