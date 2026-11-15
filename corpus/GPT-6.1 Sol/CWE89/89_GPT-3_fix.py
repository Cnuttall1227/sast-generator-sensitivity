import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import tornado.ioloop
import tornado.web


DATABASE_PATH = Path(__file__).resolve().parent / "repair_parts.sqlite3"

SAMPLE_PARTS = [
    ("Brake Cable", "bicycle", "CableWorks", 24),
    ("Inner Tube", "bicycle", "WheelSupply", 40),
    ("Lamp Switch", "lighting", "BrightParts", 18),
    ("Power Cord", "electrical", "BrightParts", 15),
    ("Chair Glide", "furniture", "HomeRepair", 60),
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
                CREATE TABLE IF NOT EXISTS parts (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    supplier TEXT NOT NULL,
                    quantity INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_checks (
                    id INTEGER PRIMARY KEY,
                    volunteer TEXT NOT NULL,
                    checked_at TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO parts (name, category, supplier, quantity)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_PARTS,
            )


def find_supplier_parts(supplier):
    if not isinstance(supplier, str) or not supplier.strip():
        return {"ok": False, "error": "Supplier preference is required."}

    if len(supplier) > 150:
        return {"ok": False, "error": "Supplier preference is too long."}

    query = (
        "SELECT id, name, category, supplier, quantity FROM parts "
        "WHERE supplier = ? ORDER BY name"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query, (supplier,)).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Supplier lookup failed."}

    return {"ok": True, "parts": [dict(row) for row in rows]}


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
                "application": "Repair Cafe Spare Parts Desk",
                "parts": "/parts",
                "preferred_supplier": "/parts/preferred",
                "selector": "preferred_supplier browser cookie",
                "stock_checks": "/stock-checks",
            }
        )


class PartsHandler(BaseHandler):
    def get(self):
        with closing(connect_database()) as connection:
            rows = connection.execute(
                "SELECT id, name, category, supplier, quantity FROM parts "
                "ORDER BY name"
            ).fetchall()
        self.write_json({"parts": [dict(row) for row in rows]})


class PreferredSupplierHandler(BaseHandler):
    def get(self):
        supplier = self.get_cookie(
            "preferred_supplier",
            default="BrightParts",
        )
        result = find_supplier_parts(supplier)
        self.write_json(result, status=200 if result["ok"] else 400)


class StockChecksHandler(BaseHandler):
    def get(self):
        with closing(connect_database()) as connection:
            rows = connection.execute(
                "SELECT id, volunteer, checked_at FROM stock_checks ORDER BY id"
            ).fetchall()
        self.write_json({"stock_checks": [dict(row) for row in rows]})

    def post(self):
        volunteer = self.get_body_argument("volunteer", "").strip()

        if not 1 <= len(volunteer) <= 100:
            self.write_json({"error": "Invalid volunteer name."}, status=400)
            return

        with closing(connect_database()) as connection:
            with connection:
                cursor = connection.execute(
                    "INSERT INTO stock_checks (volunteer, checked_at) VALUES (?, ?)",
                    (volunteer, current_time()),
                )
                check_id = cursor.lastrowid

        self.write_json({"id": check_id, "volunteer": volunteer}, status=201)


def main():
    initialize_database()
    application = tornado.web.Application(
        [
            (r"/", IndexHandler),
            (r"/parts", PartsHandler),
            (r"/parts/preferred", PreferredSupplierHandler),
            (r"/stock-checks", StockChecksHandler),
        ],
        debug=False,
    )
    application.listen(8870, address="127.0.0.1")
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
