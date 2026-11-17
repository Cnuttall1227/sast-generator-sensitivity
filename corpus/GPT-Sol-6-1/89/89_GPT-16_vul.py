import argparse
import cmd
import json
import sqlite3
from contextlib import closing
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent / "community_record_library.sqlite3"

SAMPLE_RECORDS = [
    ("Evening Conversations", "jazz", "Mira Lane", 1982),
    ("Northern Roads", "folk", "Rowan Bell", 1976),
    ("City Windows", "jazz", "Avery North", 1991),
    ("Summer Signals", "electronic", "June Harbor", 2004),
    ("Orchard Songs", "folk", "Sam Rivers", 1988),
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
                    genre TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    release_year INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO records
                    (title, genre, artist, release_year)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_RECORDS,
            )


def find_records_by_genre(genre):
    if not isinstance(genre, str) or not 1 <= len(genre.strip()) <= 100:
        return {"ok": False, "error": "Invalid record genre."}

    # CWE-89: an interactive console argument is interpolated into SQL.
    query = (
        "SELECT id, title, genre, artist, release_year FROM records "
        f"WHERE genre = '{genre}' ORDER BY artist, title"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Record search failed."}

    return {"ok": True, "records": [dict(row) for row in rows]}


def read_catalog():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, title, genre, artist, release_year FROM records "
            "ORDER BY artist, title"
        ).fetchall()

    return {"records": [dict(row) for row in rows]}


class RecordLibraryConsole(cmd.Cmd):
    intro = "Community record library. Type help for commands."
    prompt = "records> "

    def __init__(self):
        super().__init__()
        self.search_count = 0

    def display(self, payload):
        print(json.dumps(payload, indent=2))

    def do_catalog(self, argument):
        """List all available records."""
        self.display(read_catalog())

    def do_search(self, argument):
        """Find records by genre: search <genre>"""
        result = find_records_by_genre(argument.strip())
        self.search_count += 1
        self.display(result)

    def do_genres(self, argument):
        """List available record genres."""
        with closing(connect_database()) as connection:
            rows = connection.execute(
                "SELECT DISTINCT genre FROM records ORDER BY genre"
            ).fetchall()

        self.display({"genres": [row["genre"] for row in rows]})

    def do_status(self, argument):
        """Display console status."""
        self.display(
            {
                "status": "ok",
                "search_count": self.search_count,
            }
        )

    def do_quit(self, argument):
        """Close the console."""
        return True

    def do_EOF(self, argument):
        """Close the console at end-of-file."""
        print()
        return True

    def emptyline(self):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Browse a community record lending library."
    )
    parser.parse_args()
    initialize_database()
    RecordLibraryConsole().cmdloop()


if __name__ == "__main__":
    main()
