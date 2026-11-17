import os
import math
import logging
import ast
import operator
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, abort, jsonify, request

API_KEYS = set(filter(None, os.environ.get("PRICING_API_KEYS", "").split(",")))
MAX_FORMULA_LENGTH = 300

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pricing-rules")

app = Flask(__name__)

rules = {
    "standard": "base_price * quantity",
    "bulk": "base_price * quantity * (0.9 if quantity >= 100 else 1)",
    "member": "max(base_price * quantity * 0.95, base_price * quantity - 50)",
}

SAFE_FUNCTIONS = {
    "min": min,
    "max": max,
    "round": round,
    "abs": abs,
    "ceil": math.ceil,
    "floor": math.floor,
}
BINARY_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
COMPARE_OPS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
}


def require_key():
    if not API_KEYS or request.headers.get("X-Api-Key", "") not in API_KEYS:
        abort(401, description="API key required")


def money(value):
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def evaluate_formula(formula, variables):
    if len(formula) > MAX_FORMULA_LENGTH:
        raise ValueError("formula is too long")
    tree = ast.parse(formula, mode="eval")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, bool)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in variables:
                return variables[node.id]
            raise ValueError(f"unknown name {node.id!r}")
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 10 or abs(left) > 1e6):
                raise ValueError("exponent too large")
            return BINARY_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPS:
            return UNARY_OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.BoolOp):
            values = [ev(v) for v in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare) and all(type(op) in COMPARE_OPS for op in node.ops):
            left = ev(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = ev(comparator)
                if not COMPARE_OPS[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return ev(node.body) if ev(node.test) else ev(node.orelse)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in SAFE_FUNCTIONS and not node.keywords):
            return SAFE_FUNCTIONS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"{type(node).__name__} is not allowed in formulas")

    result = ev(tree)
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise ValueError("formula must produce a number")
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("formula produced an invalid number")
    if result < 0:
        raise ValueError("formula produced a negative price")
    return result


def order_variables(payload):
    try:
        return {
            "base_price": float(payload["base_price"]),
            "quantity": int(payload["quantity"]),
            "weight_kg": float(payload.get("weight_kg", 0)),
            "is_member": bool(payload.get("is_member", False)),
        }
    except (KeyError, TypeError, ValueError):
        abort(400, description="base_price and quantity are required numbers")


@app.get("/health")
def health():
    return jsonify(status="ok", rules=len(rules))


@app.get("/rules")
def list_rules():
    require_key()
    return jsonify(rules=rules)


@app.put("/rules/<name>")
def save_rule(name):
    require_key()
    if not name.replace("-", "").isalnum() or len(name) > 40:
        abort(400, description="rule names may use letters, digits and -")
    payload = request.get_json(silent=True) or {}
    formula = str(payload.get("formula", "")).strip()
    if not formula or len(formula) > MAX_FORMULA_LENGTH:
        abort(400, description=f"formula must be 1-{MAX_FORMULA_LENGTH} characters")
    sample = {"base_price": 10.0, "quantity": 1, "weight_kg": 1.0, "is_member": False}
    try:
        evaluate_formula(formula, sample)
    except Exception as exc:
        abort(400, description=f"formula failed a test run: {exc}")
    rules[name] = formula
    log.info("Saved pricing rule %s", name)
    return jsonify(name=name, formula=formula), 201


@app.post("/quote")
def quote():
    require_key()
    payload = request.get_json(silent=True) or {}
    rule_name = payload.get("rule", "standard")
    formula = rules.get(rule_name)
    if formula is None:
        abort(404, description="unknown pricing rule")
    variables = order_variables(payload)
    try:
        total = evaluate_formula(formula, variables)
    except (ValueError, ZeroDivisionError, TypeError, NameError) as exc:
        abort(422, description=f"could not price this order: {exc}")
    return jsonify(rule=rule_name, total=money(total), currency="USD")


@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(404)
@app.errorhandler(422)
def json_error(error):
    return jsonify(error=getattr(error, "description", str(error))), error.code


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))