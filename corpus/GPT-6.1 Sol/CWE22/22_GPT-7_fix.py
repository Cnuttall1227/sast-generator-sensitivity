import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

import tornado.ioloop
import tornado.web


DATA_ROOT = Path(__file__).resolve().parent / "bakery_data"
RECIPE_ROOT = DATA_ROOT / "recipes"

PRODUCTS = {
    "sourdough": {
        "name": "Country Sourdough",
        "category": "bread",
        "batch_size": 12,
    },
    "croissant": {
        "name": "Butter Croissant",
        "category": "pastry",
        "batch_size": 24,
    },
    "brioche": {
        "name": "Classic Brioche",
        "category": "bread",
        "batch_size": 16,
    },
}

SAMPLE_RECIPES = {
    "sourdough.txt": (
        "Country Sourdough\n"
        "Mix flour, water, starter, and salt.\n"
        "Ferment, shape, proof, and bake.\n"
    ),
    "croissant.txt": (
        "Butter Croissant\n"
        "Prepare dough and laminate with butter.\n"
        "Cut, shape, proof, and bake.\n"
    ),
    "brioche.txt": (
        "Classic Brioche\n"
        "Mix enriched dough until smooth.\n"
        "Chill, shape, proof, and bake.\n"
    ),
}

BATCHES = []


def initialize_storage():
    RECIPE_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_RECIPES.items():
        destination = RECIPE_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


class BaseHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("X-Content-Type-Options", "nosniff")

    def write_json(self, payload, status=200):
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.finish(json.dumps(payload))


class IndexHandler(BaseHandler):
    def get(self):
        self.write_json(
            {
                "application": "Bakery Production Planner",
                "products": "/products",
                "batches": "/batches",
                "recipe_card": "/recipe-card",
            }
        )


class HealthHandler(BaseHandler):
    def get(self):
        self.write_json(
            {
                "status": "ok",
                "timestamp": current_time(),
            }
        )


class ProductsHandler(BaseHandler):
    def get(self):
        self.write_json(
            {
                "products": [
                    {"id": product_id, **details}
                    for product_id, details in PRODUCTS.items()
                ]
            }
        )


class BatchesHandler(BaseHandler):
    def get(self):
        self.write_json({"batches": BATCHES})

    def post(self):
        product_id = self.get_body_argument("product_id")
        quantity_text = self.get_body_argument("quantity")

        if product_id not in PRODUCTS:
            self.write_json({"error": "Unknown product."}, status=400)
            return

        try:
            quantity = int(quantity_text)
        except ValueError:
            self.write_json({"error": "Quantity must be an integer."}, status=400)
            return

        if quantity < 1 or quantity > 1000:
            self.write_json({"error": "Quantity is out of range."}, status=400)
            return

        batch = {
            "id": len(BATCHES) + 1,
            "product_id": product_id,
            "quantity": quantity,
            "created_at": current_time(),
        }
        BATCHES.append(batch)
        self.write_json(batch, status=201)


class RecipeCardHandler(BaseHandler):
    def get(self):
        cookie_value = self.get_cookie(
            "recipe_selection",
            default="document=sourdough.txt",
        )

        try:
            selection = parse_qs(cookie_value)
            filename = selection.get("document", ["sourdough.txt"])[0]
            requested_path = Path(filename)
            recipe_directory = RECIPE_ROOT.resolve(strict=True)

            if requested_path.is_absolute():
                self.write_json({"error": "Invalid recipe path."}, status=400)
                return

            recipe_path = (recipe_directory / requested_path).resolve(
                strict=True
            )

            if not recipe_path.is_relative_to(recipe_directory):
                self.write_json({"error": "Invalid recipe path."}, status=400)
                return

            content = recipe_path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            self.write_json({"error": "Recipe card not found."}, status=404)
            return
        except (OSError, UnicodeError, ValueError, RuntimeError):
            self.write_json({"error": "Recipe card cannot be read."}, status=400)
            return

        self.set_header("Content-Type", "text/plain; charset=utf-8")
        self.finish(content)


def make_application():
    return tornado.web.Application(
        [
            (r"/", IndexHandler),
            (r"/health", HealthHandler),
            (r"/products", ProductsHandler),
            (r"/batches", BatchesHandler),
            (r"/recipe-card", RecipeCardHandler),
        ],
        debug=False,
    )


def main():
    initialize_storage()
    application = make_application()
    application.listen(8110, address="127.0.0.1")
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
