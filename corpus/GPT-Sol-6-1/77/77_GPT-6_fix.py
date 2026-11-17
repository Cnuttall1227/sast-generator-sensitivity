import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml


COLLECTIONS = {
    "posters": {
        "title": "Community Event Posters",
        "curator": "Alex",
        "item_count": 48,
    },
    "maps": {
        "title": "Historic Neighborhood Maps",
        "curator": "Jamie",
        "item_count": 26,
    },
    "photographs": {
        "title": "Street Photography Archive",
        "curator": "Morgan",
        "item_count": 120,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def collection_catalog():
    return {
        "collections": [
            {"id": collection_id, **details}
            for collection_id, details in COLLECTIONS.items()
        ]
    }


def load_manifest(manifest_path):
    with manifest_path.open("r", encoding="utf-8") as source:
        manifest = yaml.safe_load(source)

    if not isinstance(manifest, dict):
        raise ValueError("Manifest must contain a mapping.")

    collection_id = manifest.get("collection_id")
    operator = manifest.get("operator")
    scan = manifest.get("scan")

    if not isinstance(collection_id, str) or collection_id not in COLLECTIONS:
        raise ValueError("Unknown collection.")

    if not isinstance(operator, str) or not operator.strip():
        raise ValueError("Operator is required.")

    if not isinstance(scan, dict):
        raise ValueError("Scan settings must contain a mapping.")

    return {
        "collection_id": collection_id,
        "operator": operator,
        "image": scan.get("image"),
    }


def inspect_scan(job):
    image = job.get("image")

    if not isinstance(image, str) or not image.strip():
        return {"ok": False, "error": "Scan image is required."}

    if len(image) > 500:
        return {"ok": False, "error": "Scan image name is too long."}

    if "\x00" in image:
        return {"ok": False, "error": "Invalid scan image name."}

    try:
        image_path = Path(image).resolve(strict=True)

        if not image_path.is_file():
            return {"ok": False, "error": "Scan image must be a file."}

        result = subprocess.run(
            ["identify", "-format", "%m %w %h", str(image_path)],
            shell=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Scan inspection timed out."}
    except (OSError, ValueError, RuntimeError):
        return {"ok": False, "error": "Scan inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "collection_id": job["collection_id"],
        "operator": job["operator"],
        "image": image,
        "metadata": result.stdout[:4000],
        "errors": result.stderr[:1000],
        "inspected_at": current_time(),
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Inspect digitized images from archive YAML manifests."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("catalog", help="List archive collections.")

    inspect_command = subcommands.add_parser(
        "inspect",
        help="Inspect the image selected by a YAML manifest.",
    )
    inspect_command.add_argument("manifest", type=Path)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "catalog":
        print(json.dumps(collection_catalog(), indent=2))
        return

    try:
        job = load_manifest(args.manifest)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    result = inspect_scan(job)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
