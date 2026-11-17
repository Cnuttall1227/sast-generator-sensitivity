import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import make_server

import falcon


DATABASE_PATH = Path(__file__).resolve().parent / "seed_archive.sqlite3"

SAMPLE_SEEDS = [
    ("Cherry Tomato", "vegetable", "Sunny Acres", 45),
    ("Sweet Basil", "herb", "Green Valley", 60),
    ("Blue Cornflower", "flower", "Meadow House", 35),
    ("Butterhead Lettuce", "vegetable", "Green Valley", 50),
    ("Lemon Thyme", "herb", "Sunny Acres", 25),
]


def current_time():
    return datetime.now(timezone.utc).isoformat()


def connect_database():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with closing(connect_database()) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS seeds (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    grower TEXT NOT NULL,
                    packets INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory_checks (
                    id INTEGER PRIMARY KEY,
                    volunteer TEXT NOT NULL,
                    checked_at TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO seeds (name, category, grower, packets)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_SEEDS,
            )


def find_grower_seeds(grower):
    if not isinstance(grower, str) or not grower.strip():
        return {"ok": False, "error": "Grower name is required."}

    if len(grower) > 150:
        return {"ok": False, "error": "Grower name is too long."}

    query = (
        "SELECT id, name, category, grower, packets FROM seeds "
        "WHERE grower = ? ORDER BY name"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query, (grower,)).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Grower search failed."}

    return {"ok": True, "seeds": [dict(row) for row in rows]}


class IndexResource:
    def on_get(self, req, resp):
        resp.media = {
            "application": "Community Seed Archive",
            "seeds": "/seeds",
            "grower_search": "/seeds/by-grower",
            "selector": "X-Seed-Grower header",
            "inventory_checks": "/inventory-checks",
        }


class SeedsResource:
    def on_get(self, req, resp):
        with closing(connect_database()) as connection:
            rows = connection.execute(
                "SELECT id, name, category, grower, packets FROM seeds ORDER BY name"
            ).fetchall()
        resp.media = {"seeds": [dict(row) for row in rows]}


class GrowerSearchResource:
    def on_get(self, req, resp):
        grower = req.get_header("X-Seed-Grower") or "Sunny Acres"
        result = find_grower_seeds(grower)
        resp.status = falcon.HTTP_200 if result["ok"] else falcon.HTTP_400
        resp.media = result


class InventoryChecksResource:
    def on_get(self, req, resp):
        with closing(connect_database()) as connection:
            rows = connection.execute(
                "SELECT id, volunteer, checked_at FROM inventory_checks ORDER BY id"
            ).fetchall()
        resp.media = {"inventory_checks": [dict(row) for row in rows]}

    def on_post(self, req, resp):
        payload = req.get_media()

        if not isinstance(payload, dict):
            raise falcon.HTTPBadRequest(description="Expected an object.")

        volunteer = payload.get("volunteer")

        if not isinstance(volunteer, str) or not 1 <= len(volunteer.strip()) <= 100:
            raise falcon.HTTPBadRequest(description="Invalid volunteer name.")

        with closing(connect_database()) as connection:
            with connection:
                cursor = connection.execute(
                    "INSERT INTO inventory_checks (volunteer, checked_at) "
                    "VALUES (?, ?)",
                    (volunteer.strip(), current_time()),
                )
                check_id = cursor.lastrowid

        resp.status = falcon.HTTP_201
        resp.media = {"id": check_id, "volunteer": volunteer.strip()}


def make_application():
    initialize_database()
    application = falcon.App()
    application.add_route("/", IndexResource())
    application.add_route("/seeds", SeedsResource())
    application.add_route("/seeds/by-grower", GrowerSearchResource())
    application.add_route("/inventory-checks", InventoryChecksResource())
    return application


if __name__ == "__main__":
    with make_server("127.0.0.1", 8880, make_application()) as server:
        server.serve_forever()
