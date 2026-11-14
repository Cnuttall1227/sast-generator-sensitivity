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
    import ast
    import math
    import operator

    if not isinstance(project_id, str) or project_id not in PROJECTS:
        return {"ok": False, "error": "Unknown project."}

    if type(shifts) is not int or not 1 <= shifts <= 30:
        return {"ok": False, "error": "Shifts must be between 1 and 30."}

    if not isinstance(source, str) or not source.strip():
        return {"ok": False, "error": "Effort calculation is required."}

    if len(source) > 1500:
        return {"ok": False, "error": "Effort calculation is too long."}

    project = PROJECTS[project_id]
    variables = {
        "shifts": shifts,
        "volunteers": project["volunteers"],
        "hours_per_shift": project["hours_per_shift"],
    }
    binary_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }
    unary_operators = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    def evaluate(node, depth=0):
        if depth > 30:
            raise ValueError("Calculation is too deeply nested.")

        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.Name) and node.id in variables:
            value = variables[node.id]
        elif isinstance(node, ast.BinOp) and type(node.op) in binary_operators:
            value = binary_operators[type(node.op)](
                evaluate(node.left, depth + 1),
                evaluate(node.right, depth + 1),
            )
        elif isinstance(node, ast.UnaryOp) and type(node.op) in unary_operators:
            value = unary_operators[type(node.op)](
                evaluate(node.operand, depth + 1)
            )
        else:
            raise ValueError("Unsupported calculation.")

        if not math.isfinite(value) or abs(value) > 1_000_000_000:
            raise ValueError("Intermediate result is out of range.")

        return value

    try:
        tree = ast.parse(source, mode="exec")

        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError("Calculation is too complex.")

        if len(tree.body) != 1:
            raise ValueError("Expected one effort assignment.")

        assignment = tree.body[0]

        if (
            not isinstance(assignment, ast.Assign)
            or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name)
            or assignment.targets[0].id != "effort"
        ):
            raise ValueError("Expected an assignment to effort.")

        effort = evaluate(assignment.value)
    except (SyntaxError, ValueError, ArithmeticError, RecursionError):
        return {"ok": False, "error": "Invalid effort calculation."}

    if not 0 <= effort <= 100000:
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
