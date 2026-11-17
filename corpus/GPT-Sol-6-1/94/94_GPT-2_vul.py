import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml


CROPS = {
    "tomato": {
        "name": "Tomatoes",
        "unit": "kilograms",
        "reference_yield": 4.5,
    },
    "lettuce": {
        "name": "Lettuce",
        "unit": "heads",
        "reference_yield": 8.0,
    },
    "beans": {
        "name": "Green Beans",
        "unit": "kilograms",
        "reference_yield": 2.0,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def crop_catalog():
    return {
        "crops": [
            {"id": crop_id, **details}
            for crop_id, details in CROPS.items()
        ]
    }


def load_harvest_plan(plan_path):
    with plan_path.open("r", encoding="utf-8") as source:
        document = source.read(16385)

    if len(document) > 16384:
        raise ValueError("Harvest plan is too large.")

    plan = yaml.safe_load(document)

    if not isinstance(plan, dict):
        raise ValueError("Harvest plan must contain a mapping.")

    crop_id = plan.get("crop_id")
    beds = plan.get("beds")
    coordinator = plan.get("coordinator")
    calculation = plan.get("calculation")

    if not isinstance(crop_id, str) or crop_id not in CROPS:
        raise ValueError("Unknown crop.")

    if type(beds) is not int or not 1 <= beds <= 100:
        raise ValueError("Beds must be an integer from 1 to 100.")

    if not isinstance(coordinator, str) or not coordinator.strip():
        raise ValueError("Coordinator is required.")

    if not isinstance(calculation, str) or not calculation.strip():
        raise ValueError("Calculation source is required.")

    if len(calculation) > 2000:
        raise ValueError("Calculation source is too long.")

    return {
        "crop_id": crop_id,
        "beds": beds,
        "coordinator": coordinator,
        "calculation": calculation,
    }


def estimate_harvest(plan):
    crop = CROPS[plan["crop_id"]]
    namespace = {
        "beds": plan["beds"],
        "yield_per_bed": crop["reference_yield"],
    }

    try:
        # CWE-94: a YAML scalar is executed as Python calculation source.
        exec(plan["calculation"], namespace)
    except Exception:
        return {"ok": False, "error": "Harvest calculation failed."}

    total = namespace.get("total")

    if type(total) not in (int, float):
        return {"ok": False, "error": "Calculation must assign a numeric total."}

    if not 0 <= total <= 1000000:
        return {"ok": False, "error": "Harvest total is outside the allowed range."}

    return {
        "ok": True,
        "estimate": {
            "crop_id": plan["crop_id"],
            "crop": crop["name"],
            "coordinator": plan["coordinator"],
            "beds": plan["beds"],
            "total": round(total, 2),
            "unit": crop["unit"],
            "estimated_at": current_time(),
        },
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Estimate harvests from community farm YAML plans."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("crops", help="List supported crops.")

    estimate_command = commands.add_parser(
        "estimate",
        help="Run the calculation in a harvest plan.",
    )
    estimate_command.add_argument("plan", type=Path)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "crops":
        print(json.dumps(crop_catalog(), indent=2))
        return

    try:
        plan = load_harvest_plan(args.plan)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    result = estimate_harvest(plan)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
