import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4096

DATABASE_PATH = Path(__file__).resolve().parent / "tool_library.sqlite3"

SAMPLE_TOOLS = [
    ("Cordless Drill", "power", "North Shelf", 3),
    ("Orbital Sander", "power", "North Shelf", 2),
    ("Hand Saw", "manual", "East Rack", 5),
    ("Socket Set", "manual", "East Rack", 4),
    ("Laser Level", "measurement", "Front Cabinet", 2),
    ("Measuring Tape", "measurement", "Front Cabinet", 8),
]


def current_time():
    return datetime.now(timezone.utc).isoformat()


def connect_database():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with connect_database() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tools (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                location TEXT NOT NULL,
                available INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY,
                tool_id INTEGER NOT NULL,
                borrower TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (tool_id) REFERENCES tools(id)
            )
            """
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO tools (name, category, location, available)
            VALUES (?, ?, ?, ?)
            """,
            SAMPLE_TOOLS,
        )


def search_tools(category):
    if not isinstance(category, str) or len(category) > 100:
        return {"ok": False, "error": "Invalid category."}

    query = (
        "SELECT id, name, category, location, available "
        "FROM tools WHERE category = ? ORDER BY name"
    )

    try:
        with connect_database() as connection:
            rows = connection.execute(query, (category,)).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Tool search failed."}

    return {"ok": True, "tools": [dict(row) for row in rows]}


@app.get("/")
def index():
    return jsonify(
        application="Neighborhood Tool Lending Desk",
        tools="/tools",
        search="/tools/search?category=manual",
        reservations="/reservations",
    )


@app.get("/tools")
def list_tools():
    with connect_database() as connection:
        rows = connection.execute(
            "SELECT id, name, category, location, available FROM tools ORDER BY name"
        ).fetchall()
    return jsonify(tools=[dict(row) for row in rows])


@app.get("/tools/search")
def tool_search():
    result = search_tools(request.args.get("category", ""))
    return jsonify(result), 200 if result["ok"] else 400


@app.post("/reservations")
def reserve_tool():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify(error="Expected a JSON object."), 400

    tool_id = payload.get("tool_id")
    borrower = payload.get("borrower")

    if type(tool_id) is not int or tool_id < 1:
        return jsonify(error="Invalid tool identifier."), 400

    if not isinstance(borrower, str) or not 1 <= len(borrower.strip()) <= 100:
        return jsonify(error="Invalid borrower."), 400

    with connect_database() as connection:
        tool = connection.execute(
            "SELECT id, available FROM tools WHERE id = ?",
            (tool_id,),
        ).fetchone()

        if tool is None:
            return jsonify(error="Tool not found."), 404

        if tool["available"] < 1:
            return jsonify(error="Tool is unavailable."), 409

        connection.execute(
            "UPDATE tools SET available = available - 1 WHERE id = ?",
            (tool_id,),
        )
        cursor = connection.execute(
            "INSERT INTO reservations (tool_id, borrower, created_at) VALUES (?, ?, ?)",
            (tool_id, borrower.strip(), current_time()),
        )
        reservation_id = cursor.lastrowid

    return jsonify(id=reservation_id, tool_id=tool_id), 201


@app.get("/reservations")
def list_reservations():
    with connect_database() as connection:
        rows = connection.execute(
            "SELECT id, tool_id, borrower, created_at FROM reservations ORDER BY id"
        ).fetchall()
    return jsonify(reservations=[dict(row) for row in rows])


initialize_database()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8850, debug=False)
