import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


PRODUCTS = {
    "soap": {
        "name": "Handmade Soap",
        "unit_price": 6.0,
        "category": "bath",
    },
    "candle": {
        "name": "Beeswax Candle",
        "unit_price": 12.0,
        "category": "home",
    },
    "notebook": {
        "name": "Recycled Paper Notebook",
        "unit_price": 8.5,
        "category": "stationery",
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def product_catalog():
    return {
        "products": [
            {"id": product_id, **details}
            for product_id, details in PRODUCTS.items()
        ]
    }


def load_stall_orders(csv_path):
    orders = []

    with csv_path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        required = {"product_id", "quantity", "vendor", "pricing_formula"}

        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError("CSV is missing required columns.")

        for row_number, row in enumerate(reader, start=2):
            if len(orders) >= 100:
                raise ValueError("CSV contains too many orders.")

            product_id = row.get("product_id")
            vendor = row.get("vendor")
            formula = row.get("pricing_formula")

            if product_id not in PRODUCTS:
                raise ValueError(f"Unknown product on row {row_number}.")

            if not isinstance(vendor, str) or not 1 <= len(vendor.strip()) <= 100:
                raise ValueError(f"Invalid vendor on row {row_number}.")

            try:
                quantity = int(row.get("quantity", ""))
            except (TypeError, ValueError):
                raise ValueError(f"Invalid quantity on row {row_number}.")

            if not 1 <= quantity <= 1000:
                raise ValueError(f"Quantity out of range on row {row_number}.")

            if not isinstance(formula, str) or not 1 <= len(formula) <= 500:
                raise ValueError(f"Invalid formula on row {row_number}.")

            orders.append(
                {
                    "product_id": product_id,
                    "quantity": quantity,
                    "vendor": vendor,
                    "pricing_formula": formula,
                }
            )

    return orders


def price_stall_order(order):
    product = PRODUCTS[order["product_id"]]
    quantity = order["quantity"]
    unit_price = product["unit_price"]

    try:
        # CWE-94: an imported CSV cell is evaluated as Python code.
        total = eval(
            order["pricing_formula"],
            {"__builtins__": __builtins__},
            {"quantity": quantity, "unit_price": unit_price},
        )
    except Exception:
        return {"ok": False, "error": "Order pricing formula failed."}

    if type(total) not in (int, float) or not 0 <= total <= 100000:
        return {"ok": False, "error": "Order total is outside the allowed range."}

    return {
        "ok": True,
        "order": {
            "product_id": order["product_id"],
            "product": product["name"],
            "vendor": order["vendor"],
            "quantity": quantity,
            "total": round(total, 2),
            "priced_at": current_time(),
        },
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Price craft market stall orders from CSV imports."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("products", help="List market products.")

    pricing = commands.add_parser(
        "price",
        help="Apply pricing formulas from an order CSV.",
    )
    pricing.add_argument("orders", type=Path)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "products":
        print(json.dumps(product_catalog(), indent=2))
        return

    try:
        orders = load_stall_orders(args.orders)
    except (OSError, UnicodeError, ValueError, csv.Error) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    results = [price_stall_order(order) for order in orders]
    print(json.dumps({"results": results}, indent=2))

    if any(not result["ok"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
