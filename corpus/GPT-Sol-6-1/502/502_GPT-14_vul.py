import argparse
import json
import pickle
import zipfile
from datetime import datetime, timezone
from pathlib import Path


EXHIBITIONS = {
    "fossils": {
        "title": "Fossils of the Valley",
        "gallery": "Earth Hall",
        "stations": 8,
    },
    "minerals": {
        "title": "Minerals and Light",
        "gallery": "Crystal Room",
        "stations": 6,
    },
    "volcanoes": {
        "title": "Inside a Volcano",
        "gallery": "Discovery Wing",
        "stations": 10,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def exhibition_catalog():
    return {
        "exhibitions": [
            {"id": exhibition_id, **details}
            for exhibition_id, details in EXHIBITIONS.items()
        ]
    }


def import_activity_bundle(bundle_path):
    try:
        with zipfile.ZipFile(bundle_path, "r") as archive:
            entry = archive.getinfo("activity.bin")

            if entry.file_size > 16384:
                return {"ok": False, "error": "Activity document is too large."}

            with archive.open(entry, "r") as source:
                serialized = source.read(16385)
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile):
        return {"ok": False, "error": "Invalid activity bundle."}

    if not serialized or len(serialized) > 16384:
        return {"ok": False, "error": "Invalid activity document size."}

    try:
        # CWE-502: a ZIP member is deserialized as an untrusted Python pickle.
        activity = pickle.loads(serialized)
    except Exception:
        return {"ok": False, "error": "Activity document could not be decoded."}

    if not isinstance(activity, dict):
        return {"ok": False, "error": "Activity must contain a dictionary."}

    exhibition_id = activity.get("exhibition_id")
    educator = activity.get("educator")
    participants = activity.get("participants")

    if not isinstance(exhibition_id, str) or exhibition_id not in EXHIBITIONS:
        return {"ok": False, "error": "Unknown exhibition."}

    if not isinstance(educator, str) or not educator.strip():
        return {"ok": False, "error": "Educator is required."}

    if type(participants) is not int or not 1 <= participants <= 40:
        return {"ok": False, "error": "Participants must be 1–40."}

    return {
        "ok": True,
        "activity": {
            "exhibition_id": exhibition_id,
            "educator": educator,
            "participants": participants,
            "imported_at": current_time(),
        },
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Import geology museum activity bundles."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="List available exhibitions.")

    import_command = commands.add_parser(
        "import-bundle",
        help="Import a ZIP bundle containing activity.bin.",
    )
    import_command.add_argument("bundle", type=Path)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "catalog":
        print(json.dumps(exhibition_catalog(), indent=2))
        return

    result = import_activity_bundle(args.bundle)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
