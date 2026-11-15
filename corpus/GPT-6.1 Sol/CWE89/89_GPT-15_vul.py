import json
import sqlite3
from contextlib import closing
from pathlib import Path

from sanic import Sanic
from sanic.response import json as json_response


app = Sanic("CommunityDanceClassDesk")
DATABASE_PATH = Path(__file__).resolve().parent / "dance_classes.sqlite3"

SAMPLE_CLASSES = [
    ("Evening Waltz", "ballroom", "Studio A", 20),
    ("Saturday Salsa", "latin", "Studio B", 24),
    ("Morning Ballet", "ballet", "Studio A", 16),
    ("Social Tango", "ballroom", "Studio C", 18),
    ("Beginner Bachata", "latin", "Studio B", 22),
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
                CREATE TABLE IF NOT EXISTS classes (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL UNIQUE,
                    dance_style TEXT NOT NULL,
                    studio TEXT NOT NULL,
                    capacity INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO classes
                    (title, dance_style, studio, capacity)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_CLASSES,
            )


def find_dance_classes(style):
    if not isinstance(style, str) or not 1 <= len(style.strip()) <= 100:
        return {"ok": False, "error": "Invalid dance style."}

    # CWE-89: a JSON-valued request header supplies an unchecked SQL value.
    query = (
        "SELECT id, title, dance_style, studio, capacity FROM classes "
        f"WHERE dance_style = '{style}' ORDER BY title"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Dance class search failed."}

    return {"ok": True, "classes": [dict(row) for row in rows]}


def read_catalog():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, title, dance_style, studio, capacity FROM classes "
            "ORDER BY title"
        ).fetchall()

    return {"classes": [dict(row) for row in rows]}


@app.before_server_start
async def prepare_database(application, loop):
    initialize_database()


@app.get("/")
async def index(request):
    return json_response(
        {
            "application": "Community Dance Class Desk",
            "classes": "/classes",
            "selection": "/classes/selected",
            "selector": 'X-Dance-Selection: {"style": "ballroom"}',
        }
    )


@app.get("/classes")
async def list_classes(request):
    import asyncio

    return json_response(await asyncio.to_thread(read_catalog))


@app.get("/classes/selected")
async def selected_classes(request):
    raw_selection = request.headers.get(
        "X-Dance-Selection",
        '{"style": "ballroom"}',
    )

    if len(raw_selection) > 2048:
        return json_response({"error": "Selection is too large."}, status=400)

    try:
        selection = json.loads(raw_selection)
    except (ValueError, UnicodeError, RecursionError):
        return json_response({"error": "Invalid selection JSON."}, status=400)

    if not isinstance(selection, dict):
        return json_response({"error": "Expected a selection object."}, status=400)

    import asyncio

    result = await asyncio.to_thread(
        find_dance_classes,
        selection.get("style"),
    )
    return json_response(result, status=200 if result["ok"] else 400)


@app.get("/health")
async def health(request):
    return json_response({"status": "ok"})


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8960,
        debug=False,
        single_process=True,
    )
