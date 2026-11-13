import argparse
import configparser
import json
from datetime import datetime, timezone
from pathlib import Path


DATA_ROOT = Path(__file__).resolve().parent / "repair_cafe"
BULLETIN_ROOT = DATA_ROOT / "service_bulletins"

APPLIANCES = {
    "toaster": {
        "name": "Two-Slice Toaster",
        "category": "kitchen",
        "inspection_minutes": 20,
    },
    "lamp": {
        "name": "Desk Lamp",
        "category": "lighting",
        "inspection_minutes": 15,
    },
    "fan": {
        "name": "Table Fan",
        "category": "ventilation",
        "inspection_minutes": 25,
    },
}

SAMPLE_BULLETINS = {
    "toaster.txt": (
        "Toaster service bulletin\n"
        "Disconnect power before inspection.\n"
        "Check the crumb tray and external cable condition.\n"
    ),
    "lamp.txt": (
        "Desk lamp service bulletin\n"
        "Disconnect power before inspection.\n"
        "Check the switch, plug, and bulb compatibility.\n"
    ),
    "fan.txt": (
        "Table fan service bulletin\n"
        "Disconnect power before inspection.\n"
        "Check guards and inspect the external cable.\n"
    ),
}


def initialize_storage():
    BULLETIN_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_BULLETINS.items():
        destination = BULLETIN_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


def list_appliances():
    return {
        "appliances": [
            {"id": appliance_id, **details}
            for appliance_id, details in APPLIANCES.items()
        ]
    }


def load_job(configuration_path):
    configuration = configparser.ConfigParser(interpolation=None)

    with configuration_path.open("r", encoding="utf-8") as source:
        configuration.read_file(source)

    if not configuration.has_section("job"):
        raise ValueError("Configuration requires a [job] section.")

    appliance_id = configuration.get("job", "appliance", fallback="")
    volunteer = configuration.get("job", "volunteer", fallback="").strip()

    if appliance_id not in APPLIANCES:
        raise ValueError("Unknown appliance.")

    if not volunteer:
        raise ValueError("Volunteer name is required.")

    return {
        "appliance_id": appliance_id,
        "volunteer": volunteer,
        "bulletin": configuration.get(
            "job",
            "bulletin",
            fallback=f"{appliance_id}.txt",
        ),
    }


def prepare_job(job):
    filename = job["bulletin"]

    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("Bulletin filename is required.")

    requested_path = Path(filename)

    if requested_path.is_absolute():
        raise ValueError("Invalid bulletin path.")

    try:
        bulletin_directory = BULLETIN_ROOT.resolve(strict=True)
        bulletin_path = (bulletin_directory / requested_path).resolve(
            strict=True
        )
    except RuntimeError as error:
        raise ValueError("Invalid bulletin path.") from error

    if not bulletin_path.is_relative_to(bulletin_directory):
        raise ValueError("Invalid bulletin path.")

    content = bulletin_path.read_text(encoding="utf-8")

    return {
        "appliance": APPLIANCES[job["appliance_id"]]["name"],
        "volunteer": job["volunteer"],
        "prepared_at": current_time(),
        "bulletin": content,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Prepare repair cafe jobs from INI configuration files."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser(
        "catalog",
        help="List supported appliances.",
    )

    prepare = subcommands.add_parser(
        "prepare",
        help="Read a job configuration and display its service bulletin.",
    )
    prepare.add_argument(
        "configuration",
        type=Path,
        help="INI file containing a [job] section.",
    )

    return parser


def main():
    args = build_parser().parse_args()
    initialize_storage()

    if args.command == "catalog":
        print(json.dumps(list_appliances(), indent=2))
        return

    try:
        job = load_job(args.configuration)
        prepared = prepare_job(job)
    except (OSError, UnicodeError, ValueError, configparser.Error) as error:
        print(json.dumps({"error": str(error)}))
        raise SystemExit(1)

    print(json.dumps(prepared, indent=2))


if __name__ == "__main__":
    main()
