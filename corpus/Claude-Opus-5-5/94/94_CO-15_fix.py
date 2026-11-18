import os
import json
import logging
import threading
import ast
from concurrent import futures
from datetime import datetime, timezone
from functools import lru_cache

import grpc

INVENTORY_FILE = os.environ.get("SHOP_INVENTORY", "/srv/shop/inventory.json")
LISTEN = os.environ.get("INVENTORY_LISTEN", "127.0.0.1:50071")
AUTH_TOKEN = os.environ.get("INVENTORY_TOKEN", "")
SERVICE_NAME = "shop.Inventory"
MAX_RESULTS = 200
FILTER_FIELDS = {"sku", "name", "category", "qty", "price", "reorder_at"}
FILTER_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load,
    ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Tuple, ast.List,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("inventory-service")

inventory = {}
inventory_lock = threading.Lock()


def load_inventory():
    try:
        with open(INVENTORY_FILE, "r", encoding="utf-8") as handle:
            items = json.load(handle).get("items", [])
    except (FileNotFoundError, json.JSONDecodeError):
        items = []
    with inventory_lock:
        inventory.clear()
        for item in items:
            inventory[item["sku"]] = {
                "sku": item["sku"],
                "name": item.get("name", ""),
                "category": item.get("category", ""),
                "qty": int(item.get("qty", 0)),
                "price": float(item.get("price", 0)),
                "reorder_at": int(item.get("reorder_at", 0)),
            }


def encode(message):
    return json.dumps(message).encode("utf-8")


def decode(raw):
    return json.loads(raw.decode("utf-8")) if raw else {}


def check_auth(context):
    metadata = dict(context.invocation_metadata())
    if not AUTH_TOKEN or metadata.get("authorization") != f"Bearer {AUTH_TOKEN}":
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid token")


@lru_cache(maxsize=256)
def compile_filter(expression):
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, FILTER_NODES):
            raise SyntaxError(f"{type(node).__name__} is not allowed in filters")
        if isinstance(node, ast.Name) and node.id not in FILTER_FIELDS:
            raise NameError(node.id)
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, str, bool, type(None))):
            raise SyntaxError("unsupported constant")
    return compile(tree, "<filter>", "eval")


def matches_filter(item, expression):
    if not expression:
        return True
    code = compile_filter(expression)
    fields = {key: item[key] for key in FILTER_FIELDS if key in item}
    return bool(eval(code, {"__builtins__": {}}, fields))


def query_items(expression, limit):
    with inventory_lock:
        items = list(inventory.values())
    results = []
    for item in items:
        if matches_filter(item, expression):
            results.append(item)
            if len(results) >= limit:
                break
    return results


class InventoryService:
    def Query(self, request, context):
        check_auth(context)
        expression = str(request.get("filter", "")).strip()[:200]
        limit = max(1, min(int(request.get("limit", 50)), MAX_RESULTS))
        try:
            items = query_items(expression, limit)
        except (SyntaxError, NameError, TypeError, ZeroDivisionError) as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"bad filter: {type(exc).__name__}")
        log.info("Query %r returned %d item(s)", expression, len(items))
        return {"count": len(items), "items": items}

    def LowStock(self, request, context):
        check_auth(context)
        with inventory_lock:
            low = [i for i in inventory.values() if i["qty"] <= i["reorder_at"]]
        return {"count": len(low), "items": sorted(low, key=lambda i: i["qty"])}

    def Adjust(self, request, context):
        check_auth(context)
        sku = str(request.get("sku", ""))
        try:
            delta = int(request.get("delta", 0))
        except (TypeError, ValueError):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "delta must be a whole number")
        with inventory_lock:
            item = inventory.get(sku)
            if item is None:
                context.abort(grpc.StatusCode.NOT_FOUND, "unknown sku")
            if item["qty"] + delta < 0:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, "not enough stock")
            item["qty"] += delta
            snapshot = dict(item)
        log.info("Adjusted %s by %+d", sku, delta)
        return {"item": snapshot, "at": datetime.now(timezone.utc).isoformat()}

    def Reload(self, request, context):
        check_auth(context)
        load_inventory()
        with inventory_lock:
            return {"items": len(inventory)}


def build_server():
    service = InventoryService()
    handlers = {
        name: grpc.unary_unary_rpc_method_handler(getattr(service, name), decode, encode)
        for name in ("Query", "LowStock", "Adjust", "Reload")
    }
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(SERVICE_NAME, handlers),))
    server.add_insecure_port(LISTEN)
    return server


if __name__ == "__main__":
    load_inventory()
    server = build_server()
    server.start()
    log.info("Inventory service on %s with %d item(s)", LISTEN, len(inventory))
    server.wait_for_termination()