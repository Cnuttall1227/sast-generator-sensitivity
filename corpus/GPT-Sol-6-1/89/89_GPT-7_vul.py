import json
import sqlite3
from contextlib import closing
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


DATABASE_PATH = Path(__file__).resolve().parent / "board_game_archive.sqlite3"

SAMPLE_GAMES = [
    ("Orchard Traders", "strategy", 4, 45),
    ("Harbor Lights", "cooperative", 5, 60),
    ("Pocket Railways", "strategy", 6, 30),
    ("Garden Paths", "family", 4, 25),
    ("Cloud Islands", "family", 5, 35),
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
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    maximum_players INTEGER NOT NULL,
                    duration_minutes INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO games
                    (title, category, maximum_players, duration_minutes)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_GAMES,
            )


def find_games(selection):
    if not isinstance(selection, dict):
        return {"ok": False, "error": "Selection must be an object."}

    category = selection.get("category")
    players = selection.get("players", 2)

    if not isinstance(category, str) or not 1 <= len(category.strip()) <= 100:
        return {"ok": False, "error": "Invalid category."}

    if type(players) is not int or not 1 <= players <= 20:
        return {"ok": False, "error": "Players must be between 1 and 20."}

    # CWE-89: a POST JSON field is interpolated into a SQL string literal.
    query = (
        "SELECT id, title, category, maximum_players, duration_minutes "
        f"FROM games WHERE category = '{category}' "
        "AND maximum_players >= ? ORDER BY title"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query, (players,)).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Game search failed."}

    return {"ok": True, "games": [dict(row) for row in rows]}


def read_catalog():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, title, category, maximum_players, duration_minutes "
            "FROM games ORDER BY title"
        ).fetchall()
    return {"games": [dict(row) for row in rows]}


async def index(request: Request):
    return JSONResponse(
        {
            "application": "Community Game Night Planner",
            "catalog": "/games",
            "search": "/games/select",
            "search_format": "POST JSON with category and players",
        }
    )


async def list_games(request: Request):
    return JSONResponse(await run_in_threadpool(read_catalog))


async def select_games(request: Request):
    data = bytearray()

    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 4096:
            return JSONResponse(
                {"error": "Request body is too large."},
                status_code=413,
            )

    try:
        selection = json.loads(bytes(data))
    except (ValueError, UnicodeError, RecursionError):
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    result = await run_in_threadpool(find_games, selection)
    return JSONResponse(result, status_code=200 if result["ok"] else 400)


def make_application():
    initialize_database()
    return Starlette(
        debug=False,
        routes=[
            Route("/", index),
            Route("/games", list_games),
            Route("/games/select", select_games, methods=["POST"]),
        ],
    )


app = make_application()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8900)
