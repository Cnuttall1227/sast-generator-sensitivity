import json
import sqlite3
from contextlib import closing
from pathlib import Path

import cherrypy


DATABASE_PATH = Path(__file__).resolve().parent / "repair_manuals.sqlite3"

SAMPLE_MANUALS = [
    ("City Bicycle Maintenance", "bicycles", "English", 48),
    ("Everyday Lamp Repairs", "lighting", "English", 32),
    ("Wooden Chair Restoration", "furniture", "Spanish", 64),
    ("Basic Bicycle Adjustments", "bicycles", "French", 36),
    ("Home Lighting Handbook", "lighting", "Spanish", 52),
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
                CREATE TABLE IF NOT EXISTS manuals (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL UNIQUE,
                    topic TEXT NOT NULL,
                    language TEXT NOT NULL,
                    pages INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO manuals (title, topic, language, pages)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_MANUALS,
            )


def json_response(payload, status=200):
    cherrypy.response.status = status
    cherrypy.response.headers["Content-Type"] = (
        "application/json; charset=utf-8"
    )
    cherrypy.response.headers["X-Content-Type-Options"] = "nosniff"
    return json.dumps(payload).encode("utf-8")


def find_topic_manuals(topic):
    if not isinstance(topic, str) or not 1 <= len(topic.strip()) <= 100:
        return {"ok": False, "error": "Invalid manual topic."}

    # CWE-89: a URL path segment is interpolated into a SQL query.
    query = (
        "SELECT id, title, topic, language, pages FROM manuals "
        f"WHERE topic = '{topic}' ORDER BY title"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Manual search failed."}

    return {"ok": True, "manuals": [dict(row) for row in rows]}


class TopicLookup:
    @cherrypy.expose
    def default(self, *segments, **parameters):
        if cherrypy.request.method != "GET":
            return json_response({"error": "Use GET."}, status=405)

        if len(segments) != 1:
            return json_response(
                {"error": "Supply exactly one topic path segment."},
                status=400,
            )

        result = find_topic_manuals(segments[0])
        return json_response(result, status=200 if result["ok"] else 400)


class ManualDesk:
    def __init__(self):
        self.topics = TopicLookup()

    @cherrypy.expose
    def index(self):
        return json_response(
            {
                "application": "Community Repair Manual Desk",
                "manuals": "/manuals",
                "topic_lookup": "/topics/{topic}",
                "example": "/topics/bicycles",
            }
        )

    @cherrypy.expose
    def manuals(self):
        with closing(connect_database()) as connection:
            rows = connection.execute(
                "SELECT id, title, topic, language, pages FROM manuals "
                "ORDER BY title"
            ).fetchall()

        return json_response({"manuals": [dict(row) for row in rows]})

    @cherrypy.expose
    def health(self):
        return json_response({"status": "ok"})


def main():
    initialize_database()
    cherrypy.config.update(
        {
            "server.socket_host": "127.0.0.1",
            "server.socket_port": 8910,
            "environment": "production",
        }
    )
    cherrypy.quickstart(ManualDesk())


if __name__ == "__main__":
    main()
