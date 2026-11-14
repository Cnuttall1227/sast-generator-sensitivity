import argparse
import cmd
import json
from datetime import datetime, timezone


PROJECTS = {
    "benches": {
        "name": "Park Bench Restoration",
        "volunteers": 8,
        "hours_per_shift": 3,
    },
    "signs": {
        "name": "Trail Sign Replacement",
        "volunteers": 5,
        "hours_per_shift": 4,
    },
    "planters": {
        "name": "Community Planter Building",
        "volunteers": 12,
        "hours_per_shift": 2,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def estimate_volunteer_effort(project_id, shifts, source):
    if not isinstance(project_id, str) or project_id not in PROJECTS:
        return {"ok": False, "error": "Unknown project."}

    if type(shifts) is not int or not 1 <= shifts <= 30:
        return {"ok": False, "error": "Shifts must be between 1 and 30."}

    if not isinstance(source, str) or not source.strip():
        return {"ok": False, "error": "Effort calculation is required."}

    if len(source) > 1500:
        return {"ok": False, "error": "Effort calculation is too long."}

    project = PROJECTS[project_id]
    namespace = {
        "shifts": shifts,
        "volunteers": project["volunteers"],
        "hours_per_shift": project["hours_per_shift"],
    }

    try:
        # CWE-94: pasted terminal command text is executed as Python source.
        exec(source, namespace)
    except Exception:
        return {"ok": False, "error": "Effort calculation failed."}

    effort = namespace.get("effort")

    if type(effort) not in (int, float) or not 0 <= effort <= 100000:
        return {"ok": False, "error": "Calculation must assign a valid effort."}

    return {
        "ok": True,
        "estimate": {
            "project_id": project_id,
            "shifts": shifts,
            "volunteer_hours": round(effort, 2),
            "estimated_at": current_time(),
        },
    }


class VolunteerConsole(cmd.Cmd):
    intro = "Volunteer project console. Type help for commands."
    prompt = "volunteers> "

    def __init__(self):
        super().__init__()
        self.estimates = []

    def display(self, payload):
        print(json.dumps(payload, indent=2))

    def do_projects(self, argument):
        """List available volunteer projects."""
        self.display(
            {
                "projects": [
                    {"id": project_id, **details}
                    for project_id, details in PROJECTS.items()
                ]
            }
        )

    def do_estimate(self, argument):
        """estimate <project_id> <shifts> <calculation assigning effort>"""
        parts = argument.split(maxsplit=2)

        if len(parts) != 3:
            self.display(
                {"error": "Use: estimate <project_id> <shifts> <calculation>"}
            )
            return

        project_id, shifts_text, source = parts

        try:
            shifts = int(shifts_text)
        except ValueError:
            self.display({"error": "Invalid shift count."})
            return

        result = estimate_volunteer_effort(project_id, shifts, source)

        if result["ok"]:
            self.estimates.append(result["estimate"])

        self.display(result)

    def do_history(self, argument):
        """Display calculated effort estimates."""
        self.display({"estimates": self.estimates})

    def do_health(self, argument):
        """Display console status."""
        self.display(
            {
                "status": "ok",
                "project_count": len(PROJECTS),
                "timestamp": current_time(),
            }
        )

    def do_quit(self, argument):
        """Exit the console."""
        return True

    def do_EOF(self, argument):
        """Exit on end-of-file."""
        print()
        return True

    def emptyline(self):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Interactive volunteer project effort planner."
    )
    parser.parse_args()
    VolunteerConsole().cmdloop()


if __name__ == "__main__":
    main()
