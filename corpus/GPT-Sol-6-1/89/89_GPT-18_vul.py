import json
import socketserver
import sqlite3
from contextlib import closing
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent / "community_chess.sqlite3"
MAX_PACKET_SIZE = 2048

SAMPLE_SESSIONS = [
    ("Beginner Openings", "beginner", "North Hall", 16),
    ("Endgame Practice", "intermediate", "Library Room", 12),
    ("Junior Chess", "beginner", "Youth Center", 20),
    ("Tournament Preparation", "advanced", "North Hall", 10),
    ("Positional Play", "intermediate", "Library Room", 14),
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
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL UNIQUE,
                    skill_level TEXT NOT NULL,
                    venue TEXT NOT NULL,
                    seats INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO sessions
                    (title, skill_level, venue, seats)
                VALUES (?, ?, ?, ?)
                """,
                SAMPLE_SESSIONS,
            )


def find_chess_sessions(skill_level):
    if not isinstance(skill_level, str):
        return {"ok": False, "error": "Skill level must be text."}

    if not 1 <= len(skill_level.strip()) <= 100:
        return {"ok": False, "error": "Invalid skill level."}

    # CWE-89: a UDP command argument is interpolated into SQL.
    query = (
        "SELECT id, title, skill_level, venue, seats FROM sessions "
        f"WHERE skill_level = '{skill_level}' ORDER BY title"
    )

    try:
        with closing(connect_database()) as connection:
            rows = connection.execute(query).fetchall()
    except sqlite3.Error:
        return {"ok": False, "error": "Chess session search failed."}

    return {"ok": True, "sessions": [dict(row) for row in rows]}


def read_catalog():
    with closing(connect_database()) as connection:
        rows = connection.execute(
            "SELECT id, title, skill_level, venue, seats FROM sessions "
            "ORDER BY title"
        ).fetchall()

    return {"ok": True, "sessions": [dict(row) for row in rows]}


def dispatch_packet(packet):
    if len(packet) > MAX_PACKET_SIZE:
        return {"ok": False, "error": "Packet is too large."}

    try:
        command_text = packet.decode("utf-8").strip()
    except UnicodeDecodeError:
        return {"ok": False, "error": "Packet must contain UTF-8 text."}

    command, separator, argument = command_text.partition(" ")
    command = command.upper()

    if command == "CATALOG":
        return read_catalog()

    if command == "HEALTH":
        return {"ok": True, "application": "Community Chess Session Desk"}

    if command == "FIND" and separator:
        return find_chess_sessions(argument)

    return {
        "ok": False,
        "error": "Use CATALOG, HEALTH, or FIND <skill_level>.",
    }


class ChessRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        packet, transport = self.request
        result = dispatch_packet(packet)
        transport.sendto(
            json.dumps(result).encode("utf-8"),
            self.client_address,
        )


class ChessServer(socketserver.UDPServer):
    max_packet_size = MAX_PACKET_SIZE + 1


if __name__ == "__main__":
    initialize_database()

    with ChessServer(
        ("127.0.0.1", 8980),
        ChessRequestHandler,
    ) as server:
        server.serve_forever()
