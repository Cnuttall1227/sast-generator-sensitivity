import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from xmlrpc.server import SimpleXMLRPCServer


DATABASE_PATH = Path(__file__).resolve().parent / "instrument_archive.sqlite3"

SAMPLE_INSTRUMENTS = [
    ("Student Violin", "strings", "North Campus", 6),
    ("Concert Viola", "strings", "West Campus", 3),
    ("Student Clarinet", "woodwinds", "North Campus", 4),
    ("Brass Trumpet", "brass", "East Campus", 5),
    ("Practice Flute", "woodwinds", "West Campus", 7),
]


def current_time():
    return datetime.now(timezone.utc).isoformat()


def connect_database():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with closing(connect_database()) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS instruments (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    family TEXT NOT NULL,
                    campus TEXT NOT NULL,
                    available INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS inspections (
                    id INTEGER PRIMARY KEY,
                    technician TEXT NOT NULL,
                    inspected_at TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO instruments
                    (name, family, campus, available)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_INSTRUMENTS,
            )


def find_campus_instruments(options):
    if not isinstance(options, dict):
        return {"ok": False, "error": "Options must be a structure."}

    campus = options.get("campus", "")

    if not isinstance(campus, str) or not 1 <= len(campus.strip()) <= 150:
        return {"ok": False, "error": "Invalid campus name."}

    # CWE-89: an XML-RPC structure field is interpolated into SQL.
    query = (
        "SELECT id, name, family, campus, available FROM instruments "
        f"WHERE campus = '{campus}' ORDER BY name"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Instrument search failed."}

    return {"ok": True, "instruments": [dict(row) for row in rows]}


class MusicSchoolArchive:
    def health(self):
        return {"status": "ok", "timestamp": current_time()}

    def list_instruments(self):
        with closing(connect_database()) as connection:
            rows = connection.execute(
                "SELECT id, name, family, campus, available FROM instruments "
                "ORDER BY name"
            ).fetchall()
        return {"instruments": [dict(row) for row in rows]}

    def record_inspection(self, technician):
        if not isinstance(technician, str):
            return {"ok": False, "error": "Technician must be a string."}

        technician = technician.strip()

        if not 1 <= len(technician) <= 100:
            return {"ok": False, "error": "Invalid technician name."}

        with closing(connect_database()) as connection:
            with connection:
                cursor = connection.execute(
                    "INSERT INTO inspections (technician, inspected_at) "
                    "VALUES (?, ?)",
                    (technician, current_time()),
                )
                inspection_id = cursor.lastrowid

        return {"ok": True, "inspection_id": inspection_id}

    def list_inspections(self):
        with closing(connect_database()) as connection:
            rows = connection.execute(
                "SELECT id, technician, inspected_at FROM inspections ORDER BY id"
            ).fetchall()
        return {"inspections": [dict(row) for row in rows]}


def main():
    initialize_database()
    archive = MusicSchoolArchive()

    with SimpleXMLRPCServer(
        ("127.0.0.1", 8890),
        allow_none=False,
        logRequests=True,
    ) as server:
        server.register_function(archive.health, "music.health")
        server.register_function(archive.list_instruments, "music.instruments")
        server.register_function(
            archive.record_inspection,
            "music.record_inspection",
        )
        server.register_function(
            archive.list_inspections,
            "music.inspections",
        )
        server.register_function(
            find_campus_instruments,
            "music.find_campus",
        )
        print(json.dumps({"host": "127.0.0.1", "port": 8890}))
        server.serve_forever()


if __name__ == "__main__":
    main()
