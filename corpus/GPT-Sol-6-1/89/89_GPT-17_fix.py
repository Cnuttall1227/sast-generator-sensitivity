import json
import sqlite3
from contextlib import closing
from pathlib import Path
from wsgiref.simple_server import make_server

from pyramid.config import Configurator
from pyramid.response import Response


DATABASE_PATH = Path(__file__).resolve().parent / "community_bakery.sqlite3"

SAMPLE_PRODUCTS = [
    ("Country Sourdough", "bread", "North Bakery", 12),
    ("Butter Croissant", "pastry", "Market Bakery", 24),
    ("Seeded Rye", "bread", "North Bakery", 10),
    ("Apple Turnover", "pastry", "Riverside Bakery", 18),
    ("Oat Cookie", "cookie", "Market Bakery", 36),
]


def connect_database():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with closing(connect_database()) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    bakery TEXT NOT NULL,
                    available INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO products
                    (name, category, bakery, available)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_PRODUCTS,
            )


def json_response(payload, status=200):
    return Response(
        body=json.dumps(payload).encode("utf-8"),
        status=status,
        content_type="application/json",
        charset="utf-8",
    )


def find_bakery_products(bakery):
    if not isinstance(bakery, str) or not 1 <= len(bakery.strip()) <= 100:
        return {"ok": False, "error": "Invalid bakery name."}

    query = (
        "SELECT id, name, category, bakery, available FROM products "
        "WHERE bakery = ? ORDER BY name"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query, (bakery,)).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Bakery search failed."}

    return {"ok": True, "products": [dict(row) for row in rows]}


def index(request):
    return json_response(
        {
            "application": "Community Bakery Collection Desk",
            "products": "/products",
            "selection": "/products/by-bakery",
            "request_format": "PUT body containing a UTF-8 bakery name",
        }
    )


def list_products(request):
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, name, category, bakery, available FROM products "
            "ORDER BY name"
        ).fetchall()

    return json_response({"products": [dict(row) for row in rows]})


def select_bakery(request):
    body = request.body_file.read(1025)

    if len(body) > 1024:
        return json_response({"error": "Request body is too large."}, status=413)

    try:
        bakery = body.decode("utf-8")
    except UnicodeDecodeError:
        return json_response({"error": "Bakery must be UTF-8."}, status=400)

    result = find_bakery_products(bakery)
    return json_response(result, status=200 if result["ok"] else 400)


def health(request):
    return json_response({"status": "ok"})


def make_application():
    initialize_database()

    with Configurator() as configuration:
        configuration.add_route("index", "/")
        configuration.add_route("products", "/products")
        configuration.add_route("selection", "/products/by-bakery")
        configuration.add_route("health", "/health")
        configuration.add_view(index, route_name="index", request_method="GET")
        configuration.add_view(
            list_products,
            route_name="products",
            request_method="GET",
        )
        configuration.add_view(
            select_bakery,
            route_name="selection",
            request_method="PUT",
        )
        configuration.add_view(health, route_name="health", request_method="GET")
        return configuration.make_wsgi_app()


if __name__ == "__main__":
    with make_server("127.0.0.1", 8970, make_application()) as server:
        server.serve_forever()
