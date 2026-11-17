import argparse
import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path


TRAILS = {
    "cedar": {
        "name": "Cedar Loop",
        "distance_km": 3.5,
        "elevation_m": 80,
    },
    "ridge": {
        "name": "Ridge Traverse",
        "distance_km": 8.0,
        "elevation_m": 420,
    },
    "lake": {
        "name": "Lakeside Path",
        "distance_km": 5.0,
        "elevation_m": 35,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def trail_catalog():
    return {
        "trails": [
            {"id": trail_id, **details}
            for trail_id, details in TRAILS.items()
        ]
    }


def load_walk_plan(plan_path):
    with plan_path.open("rb") as source:
        document = source.read(8193)

    if len(document) > 8192:
        raise ValueError("Walk plan is too large.")

    plan = tomllib.loads(document.decode("utf-8"))
    walk = plan.get("walk")
    timing = plan.get("timing")

    if not isinstance(walk, dict) or not isinstance(timing, dict):
        raise ValueError("The plan requires [walk] and [timing] sections.")

    trail_id = walk.get("trail_id")
    leader = walk.get("leader")
    pace = walk.get("pace_kmh")
    expression = timing.get("minutes_expression")

    if not isinstance(trail_id, str) or trail_id not in TRAILS:
        raise ValueError("Unknown trail.")

    if not isinstance(leader, str) or not 1 <= len(leader.strip()) <= 100:
        raise ValueError("Invalid walk leader.")

    if type(pace) not in (int, float) or not 1 <= pace <= 10:
        raise ValueError("Walking pace must be between 1 and 10 km/h.")

    if not isinstance(expression, str) or not 1 <= len(expression) <= 500:
        raise ValueError("Invalid timing expression.")

    return {
        "trail_id": trail_id,
        "leader": leader,
        "pace_kmh": pace,
        "minutes_expression": expression,
    }


def estimate_walk_duration(plan):
    import ast
    import math
    import operator

    trail = TRAILS[plan["trail_id"]]
    expression = plan.get("minutes_expression")

    if not isinstance(expression, str) or not expression.strip():
        return {"ok": False, "error": "Timing expression is required."}

    if len(expression) > 500:
        return {"ok": False, "error": "Timing expression is too long."}

    variables = {
        "distance": trail["distance_km"],
        "elevation": trail["elevation_m"],
        "pace": plan["pace_kmh"],
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
            raise ValueError("Expression is too deeply nested.")

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
            raise ValueError("Unsupported timing expression.")

        if type(value) not in (int, float):
            raise ValueError("Expected a numeric value.")

        if not math.isfinite(value) or abs(value) > 1_000_000_000:
            raise ValueError("Intermediate result is out of range.")

        return value

    try:
        tree = ast.parse(expression, mode="eval")

        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError("Expression is too complex.")

        minutes = evaluate(tree.body)
    except (SyntaxError, ValueError, ArithmeticError, RecursionError):
        return {"ok": False, "error": "Invalid timing expression."}

    if not 0 < minutes <= 1440:
        return {"ok": False, "error": "Walk duration must be 0–1440 minutes."}

    return {
        "ok": True,
        "walk": {
            "trail_id": plan["trail_id"],
            "trail": trail["name"],
            "leader": plan["leader"],
            "minutes": round(minutes, 1),
            "estimated_at": current_time(),
        },
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Estimate guided walks from TOML itinerary plans."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("trails", help="List available walking trails.")

    estimate = commands.add_parser(
        "estimate",
        help="Evaluate the timing expression in a walk plan.",
    )
    estimate.add_argument("plan", type=Path)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "trails":
        print(json.dumps(trail_catalog(), indent=2))
        return

    try:
        plan = load_walk_plan(args.plan)
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    result = estimate_walk_duration(plan)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
