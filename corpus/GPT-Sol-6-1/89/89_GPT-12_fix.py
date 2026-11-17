import json
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from werkzeug.serving import run_simple
from werkzeug.wrappers import Request, Response


DATABASE_PATH = Path(__file__).resolve().parent / "community_screenings.sqlite3"

SAMPLE_FILMS = [
    ("Harbor Lights", "drama", "English", 92),
    ("Mountain Letters", "documentary", "French", 84),
    ("Market Morning", "comedy", "Spanish", 78),
    ("River Seasons", "documentary", "English", 65),
    ("The Last Tram", "drama", "Spanish", 101),
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
                CREATE TABLE IF NOT EXISTS films (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL UNIQUE,
                    genre TEXT NOT NULL,
                    language TEXT NOT NULL,
                    minutes INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO films (title, genre, language, minutes)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_FILMS,
            )


def json_response(payload, status=200):
    return Response(
        json.dumps(payload),
        status=status,
        content_type="application/json; charset=utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def find_language_films(language):
    if not isinstance(language, str) or not 1 <= len(language.strip()) <= 100:
        return {"ok": False, "error": "Invalid screening language."}

    query = (
        "SELECT id, title, genre, language, minutes FROM films "
        "WHERE language = ? ORDER BY title"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query, (language,)).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Film search failed."}

    return {"ok": True, "films": [dict(row) for row in rows]}


def read_catalog():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, title, genre, language, minutes FROM films ORDER BY title"
        ).fetchall()

    return {"films": [dict(row) for row in rows]}


@Request.application
def application(request):
    if request.method != "GET":
        return json_response({"error": "Use GET."}, status=405)

    if request.path == "/":
        return json_response(
            {
                "application": "Community Cinema Screening Desk",
                "films": "/films",
                "recommendations": "/films/recommended",
                "selector": "language query parameter in the Referer URL",
            }
        )

    if request.path == "/films":
        return json_response(read_catalog())

    if request.path == "/films/recommended":
        referer = request.headers.get("Referer", "")

        if len(referer) > 2048:
            return json_response({"error": "Referer is too long."}, status=400)

        try:
            parameters = parse_qs(
                urlsplit(referer).query,
                max_num_fields=20,
            )
        except ValueError:
            return json_response({"error": "Invalid Referer URL."}, status=400)

        language = parameters.get("language", ["English"])[0]
        result = find_language_films(language)
        return json_response(result, status=200 if result["ok"] else 400)

    if request.path == "/health":
        return json_response({"status": "ok"})

    return json_response({"error": "Endpoint not found."}, status=404)


if __name__ == "__main__":
    initialize_database()
    run_simple(
        "127.0.0.1",
        8940,
        application,
        use_debugger=False,
        use_reloader=False,
    )
