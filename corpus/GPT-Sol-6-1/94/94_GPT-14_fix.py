import argparse
import json
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path


PACKAGES = {
    "basic": {
        "name": "Basic Event Package",
        "base_cost": 120,
        "per_guest": 8,
    },
    "standard": {
        "name": "Standard Event Package",
        "base_cost": 200,
        "per_guest": 12,
    },
    "premium": {
        "name": "Premium Event Package",
        "base_cost": 350,
        "per_guest": 18,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def package_catalog():
    return {
        "packages": [
            {"id": package_id, **details}
            for package_id, details in PACKAGES.items()
        ]
    }


def load_event_request(message_path):
    with message_path.open("rb") as source:
        raw_message = source.read(16385)

    if len(raw_message) > 16384:
        raise ValueError("Event request is too large.")

    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    package_id = str(message.get("X-Event-Package", "")).strip()
    organizer = str(message.get("From", "")).strip()
    formula = str(message.get("X-Budget-Formula", "")).strip()

    try:
        guests = int(str(message.get("X-Guest-Count", "")))
    except ValueError:
        raise ValueError("Invalid guest count.")

    if package_id not in PACKAGES:
        raise ValueError("Unknown event package.")

    if not organizer or len(organizer) > 200:
        raise ValueError("Invalid organizer.")

    if not 1 <= guests <= 200:
        raise ValueError("Guest count must be between 1 and 200.")

    if not formula or len(formula) > 500:
        raise ValueError("Invalid budget formula.")

    return {
        "package_id": package_id,
        "organizer": organizer,
        "guests": guests,
        "formula": formula,
    }


def calculate_event_budget(event):
    import ast
    import math
    import operator

    package = PACKAGES[event["package_id"]]
    formula = event.get("formula")

    if not isinstance(formula, str) or not formula.strip() or len(formula) > 500:
        return {"ok": False, "error": "Invalid budget formula."}

    variables = {
        "guests": event["guests"],
        "base_cost": package["base_cost"],
        "per_guest": package["per_guest"],
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
            raise ValueError("Formula is too deeply nested.")

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
            raise ValueError("Unsupported formula.")

        if type(value) not in (int, float):
            raise ValueError("Expected a numeric value.")

        if not math.isfinite(value) or abs(value) > 1_000_000_000:
            raise ValueError("Intermediate result is out of range.")

        return value

    try:
        tree = ast.parse(formula, mode="eval")

        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError("Formula is too complex.")

        budget = evaluate(tree.body)
    except (SyntaxError, ValueError, ArithmeticError, RecursionError):
        return {"ok": False, "error": "Invalid budget formula."}

    if not 0 <= budget <= 100000:
        return {"ok": False, "error": "Budget is outside the allowed range."}

    return {
        "ok": True,
        "event": {
            "package_id": event["package_id"],
            "organizer": event["organizer"],
            "guests": event["guests"],
            "budget": round(budget, 2),
            "calculated_at": current_time(),
        },
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Estimate event budgets from imported email requests."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("packages", help="List event packages.")

    calculate = commands.add_parser(
        "calculate",
        help="Evaluate the budget formula in an email request.",
    )
    calculate.add_argument("message", type=Path)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "packages":
        print(json.dumps(package_catalog(), indent=2))
        return

    try:
        event = load_event_request(args.message)
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    result = calculate_event_budget(event)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
