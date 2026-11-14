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
    import ast
    import math
    import operator

    crop = CROPS[plan["crop_id"]]
    variables = {
        "beds": plan["beds"],
        "yield_per_bed": crop["reference_yield"],
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
            raise ValueError("Calculation result is out of range.")

        return value

    source = plan.get("calculation")

    if not isinstance(source, str) or not source.strip() or len(source) > 2000:
        return {"ok": False, "error": "Invalid harvest calculation."}

    try:
        tree = ast.parse(source, mode="exec")

        if len(tree.body) != 1:
            raise ValueError("Expected one total assignment.")

        assignment = tree.body[0]

        if (
            not isinstance(assignment, ast.Assign)
            or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name)
            or assignment.targets[0].id != "total"
        ):
            raise ValueError("Expected an assignment to total.")

        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError("Calculation is too complex.")

        total = evaluate(assignment.value)
    except (SyntaxError, ValueError, ArithmeticError, RecursionError):
        return {"ok": False, "error": "Invalid harvest calculation."}

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
