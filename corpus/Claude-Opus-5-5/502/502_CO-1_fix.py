import os
import base64
import pickle
import logging
import json
from dataclasses import dataclass, field
from decimal import Decimal

from flask import Flask, jsonify, make_response, request

CART_COOKIE = "cart"
COOKIE_MAX_AGE = 60 * 60 * 24 * 14
MAX_LINE_QUANTITY = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tea-shop")

app = Flask(__name__)

CATALOG = {
    "sencha-50": {"name": "Sencha, 50 g", "price": Decimal("8.50")},
    "oolong-50": {"name": "Tieguanyin oolong, 50 g", "price": Decimal("12.00")},
    "earl-100": {"name": "Earl Grey, 100 g", "price": Decimal("9.75")},
    "chai-100": {"name": "Masala chai, 100 g", "price": Decimal("10.25")},
    "pot-glass": {"name": "Glass teapot, 600 ml", "price": Decimal("24.00")},
}


@dataclass
class Cart:
    lines: dict = field(default_factory=dict)
    promo_code: str = ""

    def add(self, sku, quantity):
        new_quantity = self.lines.get(sku, 0) + quantity
        if new_quantity <= 0:
            self.lines.pop(sku, None)
        else:
            self.lines[sku] = min(new_quantity, MAX_LINE_QUANTITY)

    def summary(self):
        items = []
        subtotal = Decimal("0")
        for sku, quantity in self.lines.items():
            product = CATALOG.get(sku)
            if product is None:
                continue
            line_total = product["price"] * quantity
            subtotal += line_total
            items.append({"sku": sku, "name": product["name"], "quantity": quantity,
                          "unit_price": str(product["price"]), "line_total": str(line_total)})
        discount = (subtotal * Decimal("0.10")).quantize(Decimal("0.01")) if self.promo_code == "STEEP10" else Decimal("0")
        return {"items": items, "subtotal": str(subtotal), "discount": str(discount),
                "total": str(subtotal - discount), "promo_code": self.promo_code or None}


def load_cart():
    raw = request.cookies.get(CART_COOKIE)
    if not raw or len(raw) > 4096:
        return Cart()
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        log.info("Discarding unreadable cart cookie")
        return Cart()
    if not isinstance(data, dict) or not isinstance(data.get("lines"), dict):
        return Cart()
    lines = {}
    for sku, quantity in data["lines"].items():
        if sku in CATALOG and type(quantity) is int and quantity > 0:
            lines[sku] = min(quantity, MAX_LINE_QUANTITY)
    promo = data.get("promo_code")
    return Cart(lines=lines, promo_code=promo if promo == "STEEP10" else "")


def save_cart(response, cart):
    payload = json.dumps({"lines": cart.lines, "promo_code": cart.promo_code}, separators=(",", ":"))
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    response.set_cookie(CART_COOKIE, encoded, max_age=COOKIE_MAX_AGE, httponly=True, samesite="Lax", secure=True)
    return response

@app.get("/products")
def products():
    return jsonify([{"sku": sku, "name": p["name"], "price": str(p["price"])} for sku, p in CATALOG.items()])


@app.get("/cart")
def view_cart():
    return jsonify(load_cart().summary())


@app.post("/cart/items")
def add_item():
    data = request.get_json(silent=True) or {}
    sku = str(data.get("sku", ""))
    if sku not in CATALOG:
        return jsonify(error="unknown product"), 404
    try:
        quantity = int(data.get("quantity", 1))
    except (TypeError, ValueError):
        return jsonify(error="quantity must be a whole number"), 400
    cart = load_cart()
    cart.add(sku, quantity)
    return save_cart(make_response(jsonify(cart.summary())), cart)


@app.post("/cart/promo")
def apply_promo():
    code = str((request.get_json(silent=True) or {}).get("code", "")).strip().upper()[:20]
    cart = load_cart()
    cart.promo_code = code if code == "STEEP10" else ""
    status = 200 if cart.promo_code else 422
    body = cart.summary() if cart.promo_code else {"error": "that code isn't valid", **cart.summary()}
    return save_cart(make_response(jsonify(body), status), cart)


@app.delete("/cart")
def clear_cart():
    response = make_response(jsonify(Cart().summary()))
    response.delete_cookie(CART_COOKIE)
    return response


@app.get("/health")
def health():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))