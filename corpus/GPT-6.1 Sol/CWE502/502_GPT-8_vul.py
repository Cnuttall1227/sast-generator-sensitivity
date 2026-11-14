import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import jsonpickle


HABITATS = {
    "woodland": {
        "name": "Woodland Bird Habitat",
        "survey_points": 6,
        "coordinator": "Alex",
    },
    "wetland": {
        "name": "Wetland Bird Habitat",
        "survey_points": 8,
        "coordinator": "Morgan",
    },
    "grassland": {
        "name": "Grassland Bird Habitat",
        "survey_points": 5,
        "coordinator": "Jamie",
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def habitat_catalog():
    return {
        "habitats": [
            {"id": habitat_id, **details}
            for habitat_id, details in HABITATS.items()
        ]
    }


def read_observation_document(document_path):
    with document_path.open("r", encoding="utf-8") as source:
        document = source.read(16385)

    if len(document) > 16384:
        raise ValueError("Observation document is too large.")

    return document


def import_observation_document(document):
    if not isinstance(document, str) or not document.strip():
        return {"ok": False, "error": "Observation document is required."}

    if len(document) > 16384:
        return {"ok": False, "error": "Observation document is too large."}

    try:
        # CWE-502: jsonpickle restores Python objects from an imported file.
        observation = jsonpickle.decode(document)
    except Exception:
        return {"ok": False, "error": "Observation could not be decoded."}

    if not isinstance(observation, dict):
        return {"ok": False, "error": "Observation must contain a dictionary."}

    habitat_id = observation.get("habitat_id")
    observer = observation.get("observer")
    species = observation.get("species")
    count = observation.get("count")

    if not isinstance(habitat_id, str) or habitat_id not in HABITATS:
        return {"ok": False, "error": "Unknown habitat."}

    if not isinstance(observer, str) or not observer.strip():
        return {"ok": False, "error": "Observer is required."}

    if not isinstance(species, str) or not species.strip():
        return {"ok": False, "error": "Species is required."}

    if type(count) is not int or not 1 <= count <= 10000:
        return {"ok": False, "error": "Count must be an integer from 1 to 10000."}

    return {
        "ok": True,
        "observation": {
            "habitat_id": habitat_id,
            "observer": observer,
            "species": species,
            "count": count,
            "imported_at": current_time(),
        },
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Import bird observations for a habitat monitoring group."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("habitats", help="List monitored habitats.")

    import_command = commands.add_parser(
        "import-observation",
        help="Import an observation document.",
    )
    import_command.add_argument("document", type=Path)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "habitats":
        print(json.dumps(habitat_catalog(), indent=2))
        return

    try:
        document = read_observation_document(args.document)
        result = import_observation_document(document)
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
