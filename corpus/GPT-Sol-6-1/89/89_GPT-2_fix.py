import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from bottle import Bottle, request, response, run


app = Bottle()
DATABASE_PATH = Path(__file__).resolve().parent / "costume_rentals.sqlite3"

SAMPLE_COSTUMES = [
    ("Velvet Cape", "historical", "medium", 4),
    ("Explorer Jacket", "adventure", "large", 3),
    ("Astronaut Suit", "science-fiction", "medium", 2),
    ("Victorian Waistcoat", "historical", "small", 5),
    ("Pirate Coat", "adventure", "medium", 3),
]


def current_time():
    return datetime.now(timezone.utc).isoformat()


def connect_database():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    with closing(connect_database()) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS costumes (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    theme TEXT NOT NULL,
                    size TEXT NOT NULL,
                    available INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fittings (
                    id INTEGER PRIMARY KEY,
                    costume_id INTEGER NOT NULL,
                    performer TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (costume_id) REFERENCES costumes(id)
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO costumes (name, theme, size, available)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_COSTUMES,
            )


def json_response(payload, status=200):
    response.status = status
    response.content_type = "application/json; charset=utf-8"
    response.set_header("X-Content-Type-Options", "nosniff")
    return json.dumps(payload)


def find_costumes(theme, size):
    if not isinstance(theme, str) or len(theme) > 100:
        return {"ok": False, "error": "Invalid theme."}

    if size not in ("small", "medium", "large"):
        return {"ok": False, "error": "Invalid costume size."}

    query = (
        "SELECT id, name, theme, size, available FROM costumes "
        "WHERE theme = ? AND size = ? ORDER BY name"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query, (theme, size)).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Costume search failed."}

    return {"ok": True, "costumes": [dict(row) for row in rows]}


@app.get("/")
def index():
    return json_response(
        {
            "application": "Community Theater Costume Desk",
            "costumes": "/costumes",
            "search": "/costumes/search",
            "search_format": "POST form fields theme and size",
            "fittings": "/fittings",
        }
    )


@app.get("/costumes")
def list_costumes():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, name, theme, size, available FROM costumes ORDER BY name"
        ).fetchall()
    return json_response({"costumes": [dict(row) for row in rows]})


@app.post("/costumes/search")
def search_costumes():
    theme = request.forms.getunicode("theme", "")
    size = request.forms.getunicode("size", "medium")
    result = find_costumes(theme, size)
    return json_response(result, status=200 if result["ok"] else 400)


@app.post("/fittings")
def create_fitting():
    performer = request.forms.getunicode("performer", "").strip()

    try:
        costume_id = int(request.forms.getunicode("costume_id", ""))
    except ValueError:
        return json_response({"error": "Invalid costume identifier."}, status=400)

    if costume_id < 1 or not 1 <= len(performer) <= 100:
        return json_response({"error": "Invalid fitting details."}, status=400)

    with closing(connect_database()) as connection:
        with connection:
            costume = connection.execute(
                "SELECT id FROM costumes WHERE id = ?",
                (costume_id,),
            ).fetchone()

            if costume is None:
                return json_response({"error": "Costume not found."}, status=404)

            cursor = connection.execute(
                "INSERT INTO fittings (costume_id, performer, created_at) "
                "VALUES (?, ?, ?)",
                (costume_id, performer, current_time()),
            )
            fitting_id = cursor.lastrowid

    return json_response({"id": fitting_id, "costume_id": costume_id}, status=201)


@app.get("/fittings")
def list_fittings():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, costume_id, performer, created_at FROM fittings ORDER BY id"
        ).fetchall()
    return json_response({"fittings": [dict(row) for row in rows]})


if __name__ == "__main__":
    initialize_database()
    run(
        app=app,
        host="127.0.0.1",
        port=8860,
        debug=False,
        reloader=False,
    )
