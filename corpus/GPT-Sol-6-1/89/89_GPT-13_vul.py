import json
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool


DATABASE_PATH = Path(__file__).resolve().parent / "community_exhibitions.sqlite3"

SAMPLE_EXHIBITIONS = [
    ("River Memories", "photography", "North Gallery", 24),
    ("Clay and Color", "ceramics", "Studio Gallery", 18),
    ("Neighborhood Faces", "photography", "Main Hall", 30),
    ("Woven Landscapes", "textiles", "North Gallery", 16),
    ("Everyday Objects", "ceramics", "Main Hall", 22),
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
                CREATE TABLE IF NOT EXISTS exhibitions (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL UNIQUE,
                    medium TEXT NOT NULL,
                    gallery TEXT NOT NULL,
                    works INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO exhibitions
                    (title, medium, gallery, works)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_EXHIBITIONS,
            )


def find_exhibitions(medium):
    if not isinstance(medium, str) or not 1 <= len(medium.strip()) <= 100:
        return {"ok": False, "error": "Invalid exhibition medium."}

    # CWE-89: a JSON PATCH operation value is interpolated into SQL.
    query = (
        "SELECT id, title, medium, gallery, works FROM exhibitions "
        f"WHERE medium = '{medium}' ORDER BY title"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Exhibition search failed."}

    return {"ok": True, "exhibitions": [dict(row) for row in rows]}


def read_catalog():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, title, medium, gallery, works FROM exhibitions "
            "ORDER BY title"
        ).fetchall()

    return {"exhibitions": [dict(row) for row in rows]}


app = FastAPI(title="Community Exhibition Planner")


@app.get("/")
def index():
    return {
        "application": "Community Exhibition Planner",
        "catalog": "/exhibitions",
        "selection": "/exhibitions/selection",
        "request_format": "PATCH array replacing /medium",
    }


@app.get("/exhibitions")
def list_exhibitions():
    return read_catalog()


@app.patch("/exhibitions/selection")
async def select_exhibitions(request: Request):
    data = bytearray()

    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 4096:
            return JSONResponse(
                {"error": "Request body is too large."},
                status_code=413,
            )

    try:
        operations = json.loads(bytes(data))
    except (ValueError, UnicodeError, RecursionError):
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    if not isinstance(operations, list):
        return JSONResponse(
            {"error": "Expected an operation array."},
            status_code=400,
        )

    medium = "photography"

    for operation in operations:
        if not isinstance(operation, dict):
            return JSONResponse(
                {"error": "Each operation must be an object."},
                status_code=400,
            )

        if (
            operation.get("op") == "replace"
            and operation.get("path") == "/medium"
        ):
            medium = operation.get("value")

    result = await run_in_threadpool(find_exhibitions, medium)
    return JSONResponse(result, status_code=200 if result["ok"] else 400)


@app.get("/health")
def health():
    return {"status": "ok"}


initialize_database()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8950)
