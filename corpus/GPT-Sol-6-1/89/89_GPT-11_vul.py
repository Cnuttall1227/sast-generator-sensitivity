import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import yaml


DATABASE_PATH = Path(__file__).resolve().parent / "local_history_archive.sqlite3"

SAMPLE_RECORDS = [
    ("Market Square Opening", "photograph", "Old Town", 1924),
    ("River Bridge Construction", "photograph", "Riverside", 1938),
    ("School Anniversary Program", "document", "Central", 1952),
    ("Orchard Harvest Festival", "poster", "Northside", 1967),
    ("Tram Route Map", "map", "Central", 1941),
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
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL UNIQUE,
                    record_type TEXT NOT NULL,
                    neighborhood TEXT NOT NULL,
                    year INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO records
                    (title, record_type, neighborhood, year)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_RECORDS,
            )


def load_archive_filter(filter_path):
    with filter_path.open("r", encoding="utf-8") as source:
        document = source.read(4097)

    if len(document) > 4096:
        raise ValueError("Archive filter is too large.")

    filters = yaml.safe_load(document)

    if not isinstance(filters, dict):
        raise ValueError("Archive filter must contain a mapping.")

    neighborhood = filters.get("neighborhood")
    earliest_year = filters.get("earliest_year", 1800)

    if not isinstance(neighborhood, str) or not 1 <= len(neighborhood.strip()) <= 100:
        raise ValueError("Invalid neighborhood.")

    if type(earliest_year) is not int or not 1800 <= earliest_year <= 2100:
        raise ValueError("Invalid earliest year.")

    return {
        "neighborhood": neighborhood,
        "earliest_year": earliest_year,
    }


def find_archive_records(filters):
    neighborhood = filters["neighborhood"]
    earliest_year = filters["earliest_year"]

    # CWE-89: a YAML filter value is interpolated into a SQL query.
    query = (
        "SELECT id, title, record_type, neighborhood, year FROM records "
        f"WHERE neighborhood = '{neighborhood}' AND year >= ? "
        "ORDER BY year, title"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query, (earliest_year,)).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Archive search failed."}

    return {"ok": True, "records": [dict(row) for row in rows]}


def read_catalog():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, title, record_type, neighborhood, year FROM records "
            "ORDER BY year, title"
        ).fetchall()

    return {"records": [dict(row) for row in rows]}


def build_parser():
    parser = argparse.ArgumentParser(
        description="Search local history records using YAML filters."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="List archive records.")

    search = commands.add_parser(
        "search",
        help="Search records with a YAML filter document.",
    )
    search.add_argument("filter", type=Path)
    return parser


def main():
    args = build_parser().parse_args()
    initialize_database()

    if args.command == "catalog":
        print(json.dumps(read_catalog(), indent=2))
        return

    try:
        filters = load_archive_filter(args.filter)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    result = find_archive_records(filters)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
