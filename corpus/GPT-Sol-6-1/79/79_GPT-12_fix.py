from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote, urlsplit


WORKSHOPS = {
    "repair": {
        "title": "Bicycle Repair Basics",
        "room": "Workshop One",
        "capacity": 12,
    },
    "safety": {
        "title": "Cycling Safety",
        "room": "Community Hall",
        "capacity": 24,
    },
    "navigation": {
        "title": "Urban Route Planning",
        "room": "Meeting Room",
        "capacity": 16,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def page(title, body):
    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        f"<title>{escape(title)}</title>"
        "</head>"
        "<body>"
        "<header><h1>Community Cycling Workshop Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/workshops">Workshops</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


class WorkshopHandler(BaseHTTPRequestHandler):
    def send_html(self, title, body, status=200):
        encoded = page(title, body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def show_index(self):
        self.send_html(
            "Cycling Workshops",
            "<h2>Learn useful cycling skills</h2>"
            "<p>Browse workshops or preview a participant certificate.</p>"
            '<p><a href="/certificates/Guest">Preview sample certificate</a></p>',
        )

    def show_workshops(self):
        items = "".join(
            "<li>"
            f"<strong>{escape(details['title'])}</strong>"
            f" — {escape(details['room'])}"
            f" — Capacity: {details['capacity']}"
            "</li>"
            for details in WORKSHOPS.values()
        )
        self.send_html(
            "Workshops",
            "<h2>Upcoming workshops</h2><ul>" + items + "</ul>",
        )

    def show_certificate(self, encoded_participant):
        participant = unquote(encoded_participant)

        if not participant.strip() or len(participant) > 150:
            self.send_html(
                "Invalid Certificate",
                "<h2>Participant name must contain 1–150 characters.</h2>",
                status=400,
            )
            return

        body = (
            "<h2>Certificate of participation</h2>"
            '<section class="certificate">'
            f"<p>Presented to <strong>{escape(participant)}</strong></p>"
            "<p>For participating in a community cycling workshop.</p>"
            "</section>"
            f"<small>Generated at {escape(current_time())}</small>"
        )
        self.send_html("Participant Certificate", body)

    def do_GET(self):
        try:
            path = urlsplit(self.path).path
        except ValueError:
            self.send_html(
                "Invalid Request",
                "<h2>Invalid request URL.</h2>",
                status=400,
            )
            return

        if path == "/":
            self.show_index()
            return

        if path == "/workshops":
            self.show_workshops()
            return

        prefix = "/certificates/"

        if path.startswith(prefix):
            self.show_certificate(path[len(prefix):])
            return

        self.send_html(
            "Not Found",
            "<h2>Page not found</h2>",
            status=404,
        )


if __name__ == "__main__":
    with HTTPServer(("127.0.0.1", 8630), WorkshopHandler) as server:
        server.serve_forever()
