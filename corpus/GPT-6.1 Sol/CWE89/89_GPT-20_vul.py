import json
import sqlite3
from contextlib import closing
from pathlib import Path

from quart import Quart, jsonify, request


app = Quart(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4096

DATABASE_PATH = Path(__file__).resolve().parent / "community_honey.sqlite3"

SAMPLE_BATCHES = [
    ("Spring Blossom", "North Apiary", "light", 42),
    ("Summer Meadow", "River Apiary", "amber", 60),
    ("Orchard Bloom", "North Apiary", "golden", 35),
    ("Wildflower Blend", "Hill Apiary", "amber", 48),
    ("Late Harvest", "River Apiary", "dark", 30),
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
                CREATE TABLE IF NOT EXISTS batches (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    apiary TEXT NOT NULL,
                    color TEXT NOT NULL,
                    jars INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO batches (name, apiary, color, jars)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_BATCHES,
            )


def find_honey_batches(apiary):
    if not isinstance(apiary, str) or not 1 <= len(apiary.strip()) <= 100:
        return {"ok": False, "error": "Invalid apiary name."}

    # CWE-89: a multipart form field is interpolated into a SQL query.
    query = (
        "SELECT id, name, apiary, color, jars FROM batches "
        f"WHERE apiary = '{apiary}' ORDER BY name"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Honey batch search failed."}

    return {"ok": True, "batches": [dict(row) for row in rows]}


def read_catalog():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, name, apiary, color, jars FROM batches ORDER BY name"
        ).fetchall()

    return {"batches": [dict(row) for row in rows]}


@app.before_serving
async def prepare_database():
    import asyncio

    await asyncio.to_thread(initialize_database)


@app.get("/")
async def index():
    return jsonify(
        application="Community Beekeeping Harvest Desk",
        catalog="/batches",
        search="/batches/search",
        search_format="multipart form field apiary",
    )


@app.get("/batches")
async def list_batches():
    import asyncio

    return jsonify(await asyncio.to_thread(read_catalog))


@app.post("/batches/search")
async def search_batches():
    if request.mimetype != "multipart/form-data":
        return jsonify(error="Expected multipart form data."), 400

    fields = await request.form
    apiary = fields.get("apiary", "")

    import asyncio

    result = await asyncio.to_thread(find_honey_batches, apiary)
    return jsonify(result), 200 if result["ok"] else 400


@app.get("/health")
async def health():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8990, debug=False)
