import argparse
import json
import sqlite3
import tomllib
from contextlib import closing
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent / "heritage_trees.sqlite3"

SAMPLE_TREES = [
    ("Old Mill Oak", "oak", "Riverside", 145),
    ("Schoolyard Elm", "elm", "Central", 90),
    ("Library Maple", "maple", "Central", 65),
    ("Hilltop Pine", "pine", "North Ridge", 110),
    ("Market Square Oak", "oak", "Old Town", 125),
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
                CREATE TABLE IF NOT EXISTS trees (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    species TEXT NOT NULL,
                    district TEXT NOT NULL,
                    estimated_age INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO trees
                    (name, species, district, estimated_age)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_TREES,
            )


def load_survey_filter(plan_path):
    with plan_path.open("rb") as source:
        document = source.read(4097)

    if len(document) > 4096:
        raise ValueError("Survey filter is too large.")

    plan = tomllib.loads(document.decode("utf-8"))
    survey = plan.get("survey")

    if not isinstance(survey, dict):
        raise ValueError("A [survey] section is required.")

    district = survey.get("district")
    minimum_age = survey.get("minimum_age", 0)

    if not isinstance(district, str) or not 1 <= len(district.strip()) <= 100:
        raise ValueError("Invalid district.")

    if type(minimum_age) is not int or not 0 <= minimum_age <= 1000:
        raise ValueError("Minimum age must be an integer from 0 to 1000.")

    return {
        "district": district,
        "minimum_age": minimum_age,
    }


def find_survey_trees(filters):
    district = filters["district"]
    minimum_age = filters["minimum_age"]

    # CWE-89: a district imported from TOML is inserted into SQL.
    query = (
        "SELECT id, name, species, district, estimated_age FROM trees "
        f"WHERE district = '{district}' AND estimated_age >= ? "
        "ORDER BY estimated_age DESC"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query, (minimum_age,)).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Tree survey search failed."}

    return {
        "ok": True,
        "trees": [dict(row) for row in rows],
    }


def list_trees():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, name, species, district, estimated_age FROM trees "
            "ORDER BY name"
        ).fetchall()

    return {"trees": [dict(row) for row in rows]}


def build_parser():
    parser = argparse.ArgumentParser(
        description="Prepare heritage tree surveys from TOML filters."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="List registered heritage trees.")

    survey = commands.add_parser(
        "survey",
        help="Find trees matching an imported TOML survey filter.",
    )
    survey.add_argument("filter", type=Path)
    return parser


def main():
    args = build_parser().parse_args()
    initialize_database()

    if args.command == "catalog":
        print(json.dumps(list_trees(), indent=2))
        return

    try:
        filters = load_survey_filter(args.filter)
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    result = find_survey_trees(filters)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
