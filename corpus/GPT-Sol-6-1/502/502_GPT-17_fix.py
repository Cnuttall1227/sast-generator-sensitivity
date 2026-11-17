import argparse
import cmd
import json
from datetime import datetime, timezone

import yaml


DESTINATIONS = {
    "harbor": {
        "name": "Harbor History Walk",
        "duration_minutes": 60,
        "capacity": 20,
    },
    "gardens": {
        "name": "Botanical Garden Walk",
        "duration_minutes": 75,
        "capacity": 16,
    },
    "oldtown": {
        "name": "Old Town Architecture Walk",
        "duration_minutes": 90,
        "capacity": 24,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def import_excursion_plan(document):
    if not isinstance(document, str) or not document.strip():
        return {"ok": False, "error": "Excursion plan is required."}

    if len(document) > 8192:
        return {"ok": False, "error": "Excursion plan is too large."}

    try:
        plan = yaml.safe_load(document)
    except (yaml.YAMLError, ValueError, UnicodeError, RecursionError):
        return {"ok": False, "error": "Excursion plan could not be decoded."}

    if not isinstance(plan, dict):
        return {"ok": False, "error": "Plan must contain a mapping."}

    destination_id = plan.get("destination_id")
    guide = plan.get("guide")
    guests = plan.get("guests")

    if not isinstance(destination_id, str) or destination_id not in DESTINATIONS:
        return {"ok": False, "error": "Unknown destination."}

    if not isinstance(guide, str) or not guide.strip():
        return {"ok": False, "error": "Guide is required."}

    if type(guests) is not int:
        return {"ok": False, "error": "Guest count must be an integer."}

    if not 1 <= guests <= DESTINATIONS[destination_id]["capacity"]:
        return {"ok": False, "error": "Guest count exceeds capacity."}

    return {
        "ok": True,
        "plan": {
            "destination_id": destination_id,
            "guide": guide,
            "guests": guests,
            "imported_at": current_time(),
        },
    }


class ExcursionConsole(cmd.Cmd):
    intro = "Excursion planning console. Type help for commands."
    prompt = "excursions> "

    def __init__(self):
        super().__init__()
        self.plans = []

    def display(self, payload):
        print(json.dumps(payload, indent=2))

    def do_destinations(self, argument):
        """List available destinations."""
        self.display(
            {
                "destinations": [
                    {"id": destination_id, **details}
                    for destination_id, details in DESTINATIONS.items()
                ]
            }
        )

    def do_import(self, argument):
        """Import a YAML plan: import {destination_id: harbor, guide: Alex, guests: 4}"""
        result = import_excursion_plan(argument)

        if result["ok"]:
            self.plans.append(result["plan"])

        self.display(result)

    def do_plans(self, argument):
        """List imported excursion plans."""
        self.display({"plans": self.plans})

    def do_health(self, argument):
        """Display console status."""
        self.display(
            {
                "status": "ok",
                "timestamp": current_time(),
                "plan_count": len(self.plans),
            }
        )

    def do_quit(self, argument):
        """Close the console."""
        return True

    def do_EOF(self, argument):
        """Close the console at end-of-file."""
        print()
        return True

    def emptyline(self):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Interactive heritage excursion planner."
    )
    parser.parse_args()
    ExcursionConsole().cmdloop()


if __name__ == "__main__":
    main()
