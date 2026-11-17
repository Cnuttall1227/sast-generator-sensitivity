import asyncio
import json
from datetime import datetime, timezone

import websockets


GAMES = {
    "ring-toss": {
        "title": "Ring Toss",
        "base_points": 10,
        "maximum_attempts": 12,
    },
    "beanbags": {
        "title": "Beanbag Challenge",
        "base_points": 15,
        "maximum_attempts": 10,
    },
    "targets": {
        "title": "Target Roll",
        "base_points": 20,
        "maximum_attempts": 8,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def calculate_round_score(game_id, hits, attempts, scoring_source):
    import ast
    import math
    import operator

    if not isinstance(game_id, str) or game_id not in GAMES:
        return {"ok": False, "error": "Unknown game."}

    game = GAMES[game_id]

    if type(attempts) is not int or not 1 <= attempts <= game["maximum_attempts"]:
        return {"ok": False, "error": "Invalid attempt count."}

    if type(hits) is not int or not 0 <= hits <= attempts:
        return {"ok": False, "error": "Invalid hit count."}

    if not isinstance(scoring_source, str) or not scoring_source.strip():
        return {"ok": False, "error": "Scoring source is required."}

    if len(scoring_source) > 1500:
        return {"ok": False, "error": "Scoring source is too long."}

    variables = {
        "hits": hits,
        "attempts": attempts,
        "base_points": game["base_points"],
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
            raise ValueError("Scoring rule is too deeply nested.")

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
            raise ValueError("Unsupported scoring rule.")

        if not math.isfinite(value) or abs(value) > 1_000_000_000:
            raise ValueError("Intermediate result is out of range.")

        return value

    try:
        tree = ast.parse(scoring_source, mode="exec")

        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError("Scoring rule is too complex.")

        if len(tree.body) != 1:
            raise ValueError("Expected one score assignment.")

        assignment = tree.body[0]

        if (
            not isinstance(assignment, ast.Assign)
            or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name)
            or assignment.targets[0].id != "score"
        ):
            raise ValueError("Expected an assignment to score.")

        score = evaluate(assignment.value)
    except (SyntaxError, ValueError, ArithmeticError, RecursionError):
        return {"ok": False, "error": "Invalid scoring rule."}

    if not 0 <= score <= 10000:
        return {"ok": False, "error": "Rule must assign a score from 0 to 10000."}

    return {
        "ok": True,
        "round": {
            "game_id": game_id,
            "hits": hits,
            "attempts": attempts,
            "score": round(score, 2),
            "calculated_at": current_time(),
        },
    }


def game_catalog():
    return {
        "ok": True,
        "games": [
            {"id": game_id, **details}
            for game_id, details in GAMES.items()
        ],
    }


def dispatch_message(payload):
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Expected a JSON object."}

    action = payload.get("action")

    if action == "games":
        return game_catalog()

    if action == "health":
        return {
            "ok": True,
            "timestamp": current_time(),
            "game_count": len(GAMES),
        }

    if action == "score":
        return calculate_round_score(
            payload.get("game_id"),
            payload.get("hits"),
            payload.get("attempts"),
            payload.get("scoring_source"),
        )

    return {"ok": False, "error": "Unknown action."}


async def handle_connection(connection):
    async for message in connection:
        try:
            payload = json.loads(message)
        except (ValueError, UnicodeError, RecursionError):
            result = {"ok": False, "error": "Invalid JSON."}
        else:
            result = await asyncio.to_thread(dispatch_message, payload)

        await connection.send(json.dumps(result))


async def main():
    async with websockets.serve(
        handle_connection,
        "127.0.0.1",
        8780,
        max_size=8192,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
