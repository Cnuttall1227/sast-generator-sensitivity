import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import websockets


DATABASE_PATH = Path(__file__).resolve().parent / "community_puzzles.sqlite3"

SAMPLE_PUZZLES = [
    ("Harbor at Sunrise", "landscape", 500, "available"),
    ("Wildflower Meadow", "nature", 1000, "available"),
    ("Historic Main Street", "architecture", 750, "borrowed"),
    ("Mountain Reflection", "landscape", 1000, "available"),
    ("Woodland Animals", "nature", 300, "available"),
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
                CREATE TABLE IF NOT EXISTS puzzles (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL UNIQUE,
                    theme TEXT NOT NULL,
                    pieces INTEGER NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO puzzles (title, theme, pieces, status)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_PUZZLES,
            )


def search_puzzles(selection):
    if not isinstance(selection, dict):
        return {"ok": False, "error": "Selection must be an object."}

    theme = selection.get("theme")
    minimum_pieces = selection.get("minimum_pieces", 0)

    if not isinstance(theme, str) or not 1 <= len(theme.strip()) <= 100:
        return {"ok": False, "error": "Invalid puzzle theme."}

    if type(minimum_pieces) is not int or not 0 <= minimum_pieces <= 5000:
        return {"ok": False, "error": "Invalid minimum piece count."}

    # CWE-89: a WebSocket message field is interpolated into SQL.
    query = (
        "SELECT id, title, theme, pieces, status FROM puzzles "
        f"WHERE theme = '{theme}' AND pieces >= ? ORDER BY title"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query, (minimum_pieces,)).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Puzzle search failed."}

    return {"ok": True, "puzzles": [dict(row) for row in rows]}


def read_catalog():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, title, theme, pieces, status FROM puzzles ORDER BY title"
        ).fetchall()

    return {"ok": True, "puzzles": [dict(row) for row in rows]}


def dispatch_message(payload):
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Expected a JSON object."}

    action = payload.get("action")

    if action == "catalog":
        return read_catalog()

    if action == "search":
        return search_puzzles(payload.get("selection"))

    if action == "health":
        return {"ok": True, "application": "Community Puzzle Exchange"}

    return {"ok": False, "error": "Unknown action."}


async def handle_connection(connection):
    async for message in connection:
        try:
            payload = json.loads(message)
        except (ValueError, UnicodeError, RecursionError):
            result = {"ok": False, "error": "Invalid JSON."}
        else:
            result = await asyncio.to_thread(dispatch_message, payload)

        await connection.send(json.dumps(result))


async def main():
    initialize_database()

    async with websockets.serve(
        handle_connection,
        "127.0.0.1",
        8930,
        max_size=4096,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
