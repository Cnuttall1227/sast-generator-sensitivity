import argparse
import configparser
import json
import sqlite3
from contextlib import closing
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent / "community_boats.sqlite3"

SAMPLE_BOATS = [
    ("Willow", "canoe", "North Dock", 2),
    ("Kingfisher", "kayak", "East Dock", 1),
    ("Heron", "rowboat", "North Dock", 4),
    ("Otter", "canoe", "West Dock", 3),
    ("Swift", "kayak", "East Dock", 2),
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
                CREATE TABLE IF NOT EXISTS boats (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    boat_type TEXT NOT NULL,
                    dock TEXT NOT NULL,
                    seats INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO boats (name, boat_type, dock, seats)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_BOATS,
            )


def load_rental_filter(path):
    with path.open("r", encoding="utf-8") as source:
        document = source.read(4097)

    if len(document) > 4096:
        raise ValueError("Rental filter is too large.")

    configuration = configparser.ConfigParser(interpolation=None)
    configuration.read_string(document)

    if not configuration.has_section("rental"):
        raise ValueError("A [rental] section is required.")

    dock = configuration.get("rental", "dock", fallback="")
    minimum_seats = configuration.getint(
        "rental",
        "minimum_seats",
        fallback=1,
    )

    if not 1 <= len(dock.strip()) <= 100:
        raise ValueError("Invalid dock name.")

    if not 1 <= minimum_seats <= 10:
        raise ValueError("Minimum seats must be between 1 and 10.")

    return {"dock": dock, "minimum_seats": minimum_seats}


def find_rental_boats(filters):
    dock = filters["dock"]
    minimum_seats = filters["minimum_seats"]

    query = (
        "SELECT id, name, boat_type, dock, seats FROM boats "
        "WHERE dock = ? AND seats >= ? ORDER BY name"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(
                query, (dock, minimum_seats)
            ).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Boat search failed."}

    return {"ok": True, "boats": [dict(row) for row in rows]}


def read_catalog():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, name, boat_type, dock, seats FROM boats ORDER BY name"
        ).fetchall()

    return {"boats": [dict(row) for row in rows]}


def build_parser():
    parser = argparse.ArgumentParser(
        description="Find community boathouse rentals using INI filters."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="List boathouse boats.")

    search = commands.add_parser(
        "search",
        help="Search boats using an imported INI rental filter.",
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
        filters = load_rental_filter(args.filter)
    except (OSError, UnicodeError, ValueError, configparser.Error) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    result = find_rental_boats(filters)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
