import os
import time
import html
import logging
from urllib.parse import quote, unquote
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SHARE_DIR = os.environ.get("DROP_DIR", "/srv/lan-drop")
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
UPLOAD_KEY = os.environ.get("DROP_UPLOAD_KEY", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lan-drop")

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>LAN drop</title>
<style>body{{font-family:sans-serif;max-width:48rem;margin:2rem auto}}
table{{width:100%;border-collapse:collapse}}td,th{{padding:.35rem;border-bottom:1px solid #eee;text-align:left}}</style>
</head><body>
<h1>LAN drop</h1>
<p>Upload with <code>curl -T file http://host:port/upload/</code></p>
{listing}
</body></html>"""


def human_size(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def safe_name(raw):
    name = os.path.basename(unquote(raw)).strip()
    if not name or name in (".", "..") or "\x00" in name or name.startswith("."):
        return None
    return name[:200]


def render_listing():
    entries = []
    for name in os.listdir(SHARE_DIR):
        path = os.path.join(SHARE_DIR, name)
        if os.path.isfile(path) and not name.startswith("."):
            stat = os.stat(path)
            entries.append((stat.st_mtime, name, stat.st_size))
    if not entries:
        return "<p>No files yet.</p>"
    rows = []
    for modified, name, size in sorted(entries, reverse=True):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(modified))
        href = html.escape(f"/files/{quote(name, safe='')}", quote=True)
        rows.append(
            f'<tr><td><a href="{href}">{html.escape(name)}</a></td>'
            f"<td>{html.escape(human_size(size))}</td><td>{html.escape(when)}</td></tr>"
        )
    return "<table><tr><th>Name</th><th>Size</th><th>Uploaded</th></tr>" + "".join(rows) + "</table>"


class DropHandler(BaseHTTPRequestHandler):
    server_version = "LanDrop/1.0"

    def send_text(self, status, text, content_type="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_text(HTTPStatus.OK, PAGE.format(listing=render_listing()), "text/html; charset=utf-8")
            return
        if self.path.startswith("/files/"):
            name = safe_name(self.path[len("/files/"):])
            path = os.path.join(SHARE_DIR, name) if name else None
            if not path or not os.path.isfile(path):
                self.send_text(HTTPStatus.NOT_FOUND, "Not found")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")
            self.send_header("Content-Length", str(os.path.getsize(path)))
            self.end_headers()
            with open(path, "rb") as handle:
                while chunk := handle.read(64 * 1024):
                    self.wfile.write(chunk)
            return
        self.send_text(HTTPStatus.NOT_FOUND, "Not found")

    def do_PUT(self):
        if UPLOAD_KEY and self.headers.get("X-Upload-Key", "") != UPLOAD_KEY:
            self.send_text(HTTPStatus.UNAUTHORIZED, "Upload key required")
            return
        if not self.path.startswith("/upload/"):
            self.send_text(HTTPStatus.NOT_FOUND, "Not found")
            return
        name = safe_name(self.path[len("/upload/"):])
        if name is None:
            self.send_text(HTTPStatus.BAD_REQUEST, "Give the file a name")
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self.send_text(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Upload must be 1 byte to 100 MB")
            return
        destination = os.path.join(SHARE_DIR, name)
        remaining = length
        with open(destination, "wb") as out:
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
        log.info("Received %s (%d bytes) from %s", name, length, self.client_address[0])
        self.send_text(HTTPStatus.CREATED, f"Stored {name}\n")

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


if __name__ == "__main__":
    os.makedirs(SHARE_DIR, exist_ok=True)
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer(("0.0.0.0", port), DropHandler)
    log.info("LAN drop serving %s on port %d", SHARE_DIR, port)
    server.serve_forever()