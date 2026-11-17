import argparse
import json
import socketserver
from datetime import datetime, timezone
from pathlib import Path


DATA_ROOT = Path(__file__).resolve().parent / "railway_archive"
BULLETIN_ROOT = DATA_ROOT / "bulletins"
MAX_PACKET_SIZE = 4096

STATIONS = {
    "elm": {
        "name": "Elm Junction",
        "platforms": 3,
        "accessible": True,
    },
    "harbor": {
        "name": "Harbor Terminal",
        "platforms": 5,
        "accessible": True,
    },
    "ridge": {
        "name": "Ridge Crossing",
        "platforms": 2,
        "accessible": False,
    },
}

SAMPLE_BULLETINS = {
    "elm.txt": (
        "Elm Junction bulletin\n"
        "Platform 2 lighting inspection scheduled.\n"
    ),
    "harbor.txt": (
        "Harbor Terminal bulletin\n"
        "Ticket office opens at 06:00.\n"
    ),
    "ridge.txt": (
        "Ridge Crossing bulletin\n"
        "Footbridge painting begins next week.\n"
    ),
}


def initialize_storage():
    BULLETIN_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_BULLETINS.items():
        destination = BULLETIN_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


def station_catalog():
    return {
        "ok": True,
        "stations": [
            {"id": station_id, **details}
            for station_id, details in STATIONS.items()
        ],
    }


def station_details(station_id):
    station = STATIONS.get(station_id)

    if station is None:
        return {"ok": False, "error": "Unknown station."}

    return {
        "ok": True,
        "station": {"id": station_id, **station},
    }


def read_bulletin(filename):
    if not isinstance(filename, str) or not filename.strip():
        return {"ok": False, "error": "Bulletin filename is required."}

    try:
        bulletin_directory = BULLETIN_ROOT.resolve(strict=True)
        requested_path = Path(filename)

        if requested_path.is_absolute():
            return {"ok": False, "error": "Invalid bulletin path."}

        bulletin_path = (bulletin_directory / requested_path).resolve(
            strict=True
        )

        if not bulletin_path.is_relative_to(bulletin_directory):
            return {"ok": False, "error": "Invalid bulletin path."}

        content = bulletin_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return {"ok": False, "error": "Bulletin not found."}
    except (OSError, UnicodeError, ValueError, RuntimeError):
        return {"ok": False, "error": "Bulletin cannot be read."}

    return {
        "ok": True,
        "filename": filename,
        "content": content,
    }


def dispatch_packet(packet):
    if len(packet) > MAX_PACKET_SIZE:
        return {"ok": False, "error": "Packet too large."}

    try:
        command_text = packet.decode("utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": "Packet must contain UTF-8 text."}

    command, separator, argument = command_text.strip().partition(" ")
    command = command.upper()
    argument = argument.strip()

    if command == "PING":
        return {"ok": True, "timestamp": current_time()}

    if command == "STATIONS":
        return station_catalog()

    if command == "STATION":
        return station_details(argument)

    if command == "BULLETIN":
        return read_bulletin(argument)

    return {"ok": False, "error": "Unknown command."}


class RailwayRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        packet, transport = self.request
        response = dispatch_packet(packet)
        encoded = json.dumps(response).encode("utf-8")

        if len(encoded) > 60000:
            encoded = json.dumps(
                {"ok": False, "error": "Response exceeds packet limit."}
            ).encode("utf-8")

        transport.sendto(encoded, self.client_address)


class RailwayServer(socketserver.UDPServer):
    max_packet_size = MAX_PACKET_SIZE + 1


def main():
    parser = argparse.ArgumentParser(
        description="Railway bulletin archive UDP service."
    )
    parser.add_argument("--port", type=int, default=8140)
    args = parser.parse_args()

    initialize_storage()

    with RailwayServer(
        ("127.0.0.1", args.port),
        RailwayRequestHandler,
    ) as server:
        print(f"Railway archive listening on 127.0.0.1:{args.port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
