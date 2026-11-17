import argparse
import csv
import json
import sqlite3
from contextlib import closing
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent / "community_textiles.sqlite3"

SAMPLE_FABRICS = [
    ("Natural Linen", "linen", "North Mill", 45),
    ("Blue Cotton", "cotton", "River Weavers", 80),
    ("Heavy Canvas", "canvas", "North Mill", 35),
    ("Printed Cotton", "cotton", "Market Textiles", 65),
    ("Soft Wool", "wool", "River Weavers", 28),
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
                CREATE TABLE IF NOT EXISTS fabrics (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    fiber TEXT NOT NULL,
                    supplier TEXT NOT NULL,
                    meters INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO fabrics (name, fiber, supplier, meters)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_FABRICS,
            )


def load_requests(csv_path):
    requests = []

    with csv_path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        required = {"supplier", "minimum_meters"}

        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError("CSV requires supplier and minimum_meters columns.")

        for row_number, row in enumerate(reader, start=2):
            if len(requests) >= 100:
                raise ValueError("CSV contains too many requests.")

            supplier = row.get("supplier")

            if not isinstance(supplier, str) or not 1 <= len(supplier.strip()) <= 100:
                raise ValueError(f"Invalid supplier on row {row_number}.")

            try:
                minimum_meters = int(row.get("minimum_meters", ""))
            except (TypeError, ValueError):
                raise ValueError(f"Invalid meter quantity on row {row_number}.")

            if not 0 <= minimum_meters <= 10000:
                raise ValueError(f"Meter quantity out of range on row {row_number}.")

            requests.append(
                {
                    "supplier": supplier,
                    "minimum_meters": minimum_meters,
                }
            )

    return requests


def find_requested_fabrics(selection):
    supplier = selection["supplier"]
    minimum_meters = selection["minimum_meters"]

    # CWE-89: a supplier imported from a CSV cell is interpolated into SQL.
    query = (
        "SELECT id, name, fiber, supplier, meters FROM fabrics "
        f"WHERE supplier = '{supplier}' AND meters >= ? ORDER BY name"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query, (minimum_meters,)).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Fabric search failed."}

    return {"ok": True, "fabrics": [dict(row) for row in rows]}


def read_catalog():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, name, fiber, supplier, meters FROM fabrics ORDER BY name"
        ).fetchall()

    return {"fabrics": [dict(row) for row in rows]}


def build_parser():
    parser = argparse.ArgumentParser(
        description="Find sewing materials from imported CSV requests."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="List available fabrics.")

    search = commands.add_parser(
        "search",
        help="Search fabrics for each request in a CSV file.",
    )
    search.add_argument("requests", type=Path)
    return parser


def main():
    args = build_parser().parse_args()
    initialize_database()

    if args.command == "catalog":
        print(json.dumps(read_catalog(), indent=2))
        return

    try:
        requests = load_requests(args.requests)
    except (OSError, UnicodeError, ValueError, csv.Error) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    results = [find_requested_fabrics(selection) for selection in requests]
    print(json.dumps({"results": results}, indent=2))

    if any(not result["ok"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
