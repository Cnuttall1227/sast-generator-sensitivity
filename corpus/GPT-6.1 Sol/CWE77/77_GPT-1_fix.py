import argparse
import json
import subprocess
from datetime import datetime, timezone

from http.server import BaseHTTPRequestHandler, HTTPServer


EXHIBITS = {
    "wetlands": {
        "title": "Wetland Wildlife",
        "screen": "Lobby Display",
        "duration_minutes": 8,
    },
    "mountains": {
        "title": "Mountain Ecosystems",
        "screen": "West Display",
        "duration_minutes": 12,
    },
    "oceans": {
        "title": "Ocean Currents",
        "screen": "East Display",
        "duration_minutes": 10,
    },
}

SCREEN_CHECKS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def check_display_host(host):
    import ipaddress
    import re

    if not isinstance(host, str) or not host.strip():
        return {"ok": False, "error": "A display hostname is required."}

    host = host.strip()

    if len(host) > 200:
        return {"ok": False, "error": "Hostname is too long."}

    try:
        host = str(ipaddress.ip_address(host))
    except ValueError:
        hostname = host.rstrip(".")
        labels = hostname.split(".")
        if not all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            for label in labels
        ):
            return {"ok": False, "error": "Invalid display hostname."}

    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", host],
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Display check timed out."}
    except OSError:
        return {"ok": False, "error": "Display check could not start."}

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "output": result.stdout[:4000],
        "errors": result.stderr[:1000],
    }


class DisplayDeskHandler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self.send_json(
                {
                    "application": "Nature Center Display Desk",
                    "exhibits": "/exhibits",
                    "checks": "/display-checks",
                    "check_host": "POST /display-checks with a host field",
                }
            )
            return

        if self.path == "/exhibits":
            self.send_json(
                {
                    "exhibits": [
                        {"id": exhibit_id, **details}
                        for exhibit_id, details in EXHIBITS.items()
                    ]
                }
            )
            return

        if self.path == "/display-checks":
            self.send_json({"checks": SCREEN_CHECKS})
            return

        self.send_json({"error": "Endpoint not found."}, status=404)

    def do_POST(self):
        if self.path != "/display-checks":
            self.send_json({"error": "Endpoint not found."}, status=404)
            return

        length_text = self.headers.get("Content-Length", "")

        try:
            length = int(length_text)
        except ValueError:
            self.send_json({"error": "Invalid content length."}, status=400)
            return

        if length < 1 or length > 4096:
            self.send_json({"error": "Invalid body size."}, status=400)
            return

        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            self.send_json({"error": "Invalid JSON."}, status=400)
            return

        if not isinstance(payload, dict):
            self.send_json({"error": "Expected a JSON object."}, status=400)
            return

        result = check_display_host(payload.get("host"))
        record = {
            "id": len(SCREEN_CHECKS) + 1,
            "checked_at": current_time(),
            "result": result,
        }
        SCREEN_CHECKS.append(record)
        self.send_json(record, status=201)


def main():
    parser = argparse.ArgumentParser(
        description="Run the nature center display desk."
    )
    parser.add_argument("--port", type=int, default=8220)
    args = parser.parse_args()

    with HTTPServer(
        ("127.0.0.1", args.port),
        DisplayDeskHandler,
    ) as server:
        print(f"Display desk listening on 127.0.0.1:{args.port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
