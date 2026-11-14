import argparse
import configparser
import json
from datetime import datetime, timezone
from pathlib import Path


EXHIBITS = {
    "reef": {
        "title": "Coral Reef",
        "daily_feed_grams": 240,
        "animals": 18,
    },
    "river": {
        "title": "River Habitat",
        "daily_feed_grams": 180,
        "animals": 24,
    },
    "kelp": {
        "title": "Kelp Forest",
        "daily_feed_grams": 320,
        "animals": 12,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def exhibit_catalog():
    return {
        "exhibits": [
            {"id": exhibit_id, **details}
            for exhibit_id, details in EXHIBITS.items()
        ]
    }


def load_feeding_plan(path):
    configuration = configparser.ConfigParser(interpolation=None)

    with path.open("r", encoding="utf-8") as source:
        document = source.read(8193)

    if len(document) > 8192:
        raise ValueError("Feeding plan is too large.")

    configuration.read_string(document)

    if not configuration.has_section("feeding"):
        raise ValueError("A [feeding] section is required.")

    exhibit_id = configuration.get("feeding", "exhibit", fallback="")
    keeper = configuration.get("feeding", "keeper", fallback="").strip()
    days = configuration.getint("feeding", "days", fallback=1)
    adjustment = configuration.get("feeding", "adjustment", fallback="")

    if exhibit_id not in EXHIBITS:
        raise ValueError("Unknown exhibit.")

    if not keeper or len(keeper) > 100:
        raise ValueError("Keeper must contain 1–100 characters.")

    if not 1 <= days <= 30:
        raise ValueError("Days must be between 1 and 30.")

    if not adjustment.strip() or len(adjustment) > 1500:
        raise ValueError("Adjustment must contain 1–1500 characters.")

    return {
        "exhibit_id": exhibit_id,
        "keeper": keeper,
        "days": days,
        "adjustment": adjustment,
    }


def prepare_feeding_schedule(plan):
    exhibit = EXHIBITS[plan["exhibit_id"]]
    namespace = {
        "daily_grams": exhibit["daily_feed_grams"],
        "days": plan["days"],
        "animals": exhibit["animals"],
    }

    try:
        # CWE-94: an INI configuration value becomes executable Python source.
        program = compile(plan["adjustment"], "<feeding-adjustment>", "exec")
        exec(program, namespace)
    except Exception:
        return {"ok": False, "error": "Feeding adjustment failed."}

    total_grams = namespace.get("total_grams")

    if type(total_grams) not in (int, float):
        return {"ok": False, "error": "Adjustment must assign numeric total_grams."}

    if not 0 <= total_grams <= 100000:
        return {"ok": False, "error": "Feed quantity is outside the allowed range."}

    return {
        "ok": True,
        "schedule": {
            "exhibit_id": plan["exhibit_id"],
            "exhibit": exhibit["title"],
            "keeper": plan["keeper"],
            "days": plan["days"],
            "total_grams": round(total_grams, 2),
            "prepared_at": current_time(),
        },
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Prepare aquarium feeding schedules from INI plans."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("exhibits", help="List aquarium exhibits.")

    prepare = commands.add_parser(
        "prepare",
        help="Apply the adjustment in an INI feeding plan.",
    )
    prepare.add_argument("plan", type=Path)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "exhibits":
        print(json.dumps(exhibit_catalog(), indent=2))
        return

    try:
        plan = load_feeding_plan(args.plan)
    except (OSError, UnicodeError, ValueError, configparser.Error) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    result = prepare_feeding_schedule(plan)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
