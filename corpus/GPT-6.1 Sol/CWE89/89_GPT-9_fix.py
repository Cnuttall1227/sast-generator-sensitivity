import json
import sqlite3
from contextlib import closing
from pathlib import Path
from xml.etree import ElementTree

from aiohttp import web


DATABASE_PATH = Path(__file__).resolve().parent / "ceramic_glazes.sqlite3"
routes = web.RouteTableDef()

SAMPLE_GLAZES = [
    ("Ocean Blue", "blue", 6, "gloss"),
    ("Forest Green", "green", 6, "matte"),
    ("Cloud White", "white", 5, "satin"),
    ("Midnight Blue", "blue", 10, "matte"),
    ("Moss Green", "green", 5, "gloss"),
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
                CREATE TABLE IF NOT EXISTS glazes (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    color TEXT NOT NULL,
                    firing_cone INTEGER NOT NULL,
                    finish TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO glazes (name, color, firing_cone, finish)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_GLAZES,
            )


def find_glazes(color, cone):
    if not isinstance(color, str) or not 1 <= len(color.strip()) <= 100:
        return {"ok": False, "error": "Invalid glaze color."}

    if type(cone) is not int or not 1 <= cone <= 12:
        return {"ok": False, "error": "Firing cone must be between 1 and 12."}

    query = (
        "SELECT id, name, color, firing_cone, finish FROM glazes "
        "WHERE color = ? AND firing_cone = ? ORDER BY name"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query, (color, cone)).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Glaze search failed."}

    return {"ok": True, "glazes": [dict(row) for row in rows]}


def read_catalog():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, name, color, firing_cone, finish FROM glazes "
            "ORDER BY name"
        ).fetchall()

    return {"glazes": [dict(row) for row in rows]}


@routes.get("/")
async def index(request):
    return web.json_response(
        {
            "application": "Community Pottery Glaze Catalog",
            "catalog": "/glazes",
            "search": "/glazes/search",
            "request_format": "POST XML with color and cone elements",
        }
    )


@routes.get("/glazes")
async def list_glazes(request):
    import asyncio

    return web.json_response(await asyncio.to_thread(read_catalog))


@routes.post("/glazes/search")
async def search_glazes(request):
    body = await request.read()

    try:
        selection = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return web.json_response({"error": "Invalid XML."}, status=400)

    if selection.tag != "selection":
        return web.json_response(
            {"error": "Expected a selection element."},
            status=400,
        )

    color = selection.findtext("color", default="")

    try:
        cone = int(selection.findtext("cone", default=""))
    except ValueError:
        return web.json_response({"error": "Invalid firing cone."}, status=400)

    import asyncio

    result = await asyncio.to_thread(find_glazes, color, cone)
    return web.json_response(result, status=200 if result["ok"] else 400)


def make_application():
    initialize_database()
    application = web.Application(client_max_size=4096)
    application.add_routes(routes)
    return application


if __name__ == "__main__":
    web.run_app(make_application(), host="127.0.0.1", port=8920)
