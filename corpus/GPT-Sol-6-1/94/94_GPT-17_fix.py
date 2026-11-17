import json
from datetime import datetime, timezone

from quart import Quart, jsonify, request


app = Quart(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8192

PACKAGES = {
    "small": {
        "name": "Small Seed Packet",
        "seeds_per_packet": 20,
        "reserve_percent": 5,
    },
    "medium": {
        "name": "Medium Seed Packet",
        "seeds_per_packet": 50,
        "reserve_percent": 8,
    },
    "large": {
        "name": "Large Seed Packet",
        "seeds_per_packet": 100,
        "reserve_percent": 10,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def calculate_seed_allocation(package_id, packets, formula):
    import ast
    import math
    import operator

    if not isinstance(package_id, str) or package_id not in PACKAGES:
        return {"ok": False, "error": "Unknown packet size."}

    if type(packets) is not int or not 1 <= packets <= 500:
        return {"ok": False, "error": "Packets must be between 1 and 500."}

    if not isinstance(formula, str) or not formula.strip():
        return {"ok": False, "error": "Allocation formula is required."}

    if len(formula) > 500:
        return {"ok": False, "error": "Allocation formula is too long."}

    package = PACKAGES[package_id]
    variables = {
        "packets": packets,
        "seeds_per_packet": package["seeds_per_packet"],
        "reserve_percent": package["reserve_percent"],
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
            raise ValueError("Unsupported allocation formula.")

        if not math.isfinite(value) or abs(value) > 1_000_000_000:
            raise ValueError("Intermediate result is out of range.")

        return value

    try:
        tree = ast.parse(formula, mode="eval")

        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError("Formula is too complex.")

        seeds = evaluate(tree.body)
    except (SyntaxError, ValueError, ArithmeticError, RecursionError):
        return {"ok": False, "error": "Invalid allocation formula."}

    if not 0 <= seeds <= 100000:
        return {"ok": False, "error": "Seed allocation is outside the allowed range."}

    return {
        "ok": True,
        "allocation": {
            "package_id": package_id,
            "packets": packets,
            "seeds": round(seeds),
            "calculated_at": current_time(),
        },
    }


@app.get("/")
async def index():
    return jsonify(
        application="Community Seed Packing Desk",
        packages="/packages",
        allocation="/allocations",
        request_format="multipart form fields package_id, packets, and formula",
        example_formula="packets * seeds_per_packet * (1 + reserve_percent / 100)",
    )


@app.get("/packages")
async def list_packages():
    return jsonify(
        packages=[
            {"id": package_id, **details}
            for package_id, details in PACKAGES.items()
        ]
    )


@app.post("/allocations")
async def allocate_seeds():
    if request.mimetype != "multipart/form-data":
        return jsonify(error="Expected multipart form data."), 400

    fields = await request.form
    package_id = fields.get("package_id", "")
    formula = fields.get("formula", "")

    try:
        packets = int(fields.get("packets", ""))
    except ValueError:
        return jsonify(error="Invalid packet count."), 400

    import asyncio

    result = await asyncio.to_thread(
        calculate_seed_allocation,
        package_id,
        packets,
        formula,
    )
    return jsonify(result), 200 if result["ok"] else 400


@app.get("/health")
async def health():
    return jsonify(
        status="ok",
        package_count=len(PACKAGES),
        timestamp=current_time(),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8820, debug=False)
