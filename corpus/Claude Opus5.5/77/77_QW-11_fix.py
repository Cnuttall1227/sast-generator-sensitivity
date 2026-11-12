import os
import json
import time
import logging
import re

import pexpect
import tornado.ioloop
import tornado.web
import tornado.websocket

PIP_BINARY = os.environ.get("PKGINFO_PIP", "pip")
INDEX_URL = os.environ.get("PKGINFO_INDEX", "https://pypi.org/simple")
COMMAND_TIMEOUT = 45
MAX_CLIENTS = 25
RATE_LIMIT_SECONDS = 3
PACKAGE_PATTERN = re.compile(r"^([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9._-]{0,98}[A-Za-z0-9])$")


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pkginfo")

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Package versions</title></head>
<body>
<h1>Package version lookup</h1>
<input id="pkg" placeholder="package name"><button id="go">Look up</button>
<pre id="out"></pre>
<script>
const ws = new WebSocket(`ws://${location.host}/ws`);
const out = document.getElementById("out");
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  out.textContent += (msg.line || msg.status || msg.error) + "\\n";
};
document.getElementById("go").onclick = () => {
  out.textContent = "";
  ws.send(JSON.stringify({action: "versions", package: document.getElementById("pkg").value}));
};
</script>
</body></html>"""


class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.write(PAGE)


class HealthHandler(tornado.web.RequestHandler):
    def get(self):
        self.write({"status": "ok", "clients": len(LookupSocket.clients)})


def stream_versions(package, emit):
    if not PACKAGE_PATTERN.fullmatch(package):
        emit({"error": "Invalid package name"})
        return 2
    args = [
        "index", "versions", package,
        "--index-url", INDEX_URL,
        "--disable-pip-version-check",
    ]
    child = pexpect.spawn(PIP_BINARY, args, encoding="utf-8", timeout=COMMAND_TIMEOUT)
    try:
        for line in child:
            line = line.rstrip()
            if line:
                emit({"line": line})
    except pexpect.TIMEOUT:
        emit({"error": "lookup timed out"})
    finally:
        child.close()
    return child.exitstatus


class LookupSocket(tornado.websocket.WebSocketHandler):
    clients = set()

    def check_origin(self, origin):
        host = self.request.headers.get("Host", "")
        return origin.endswith("://" + host)

    def open(self):
        if len(self.clients) >= MAX_CLIENTS:
            self.close(code=1013, reason="Server busy")
            return
        self.clients.add(self)
        self.last_request = 0.0
        log.info("Client connected (%d total)", len(self.clients))

    def on_close(self):
        self.clients.discard(self)

    def emit(self, payload):
        if self.ws_connection is not None:
            self.write_message(json.dumps(payload))

    async def on_message(self, message):
        now = time.monotonic()
        if now - self.last_request < RATE_LIMIT_SECONDS:
            self.emit({"error": "Slow down"})
            return
        self.last_request = now
        try:
            request = json.loads(message)
        except json.JSONDecodeError:
            self.emit({"error": "Invalid JSON"})
            return
        if request.get("action") != "versions":
            self.emit({"error": "Unknown action"})
            return
        package = str(request.get("package", "")).strip()
        if not package or len(package) > 100:
            self.emit({"error": "Package name must be 1-100 characters"})
            return
        self.emit({"status": f"Looking up {package}..."})
        loop = tornado.ioloop.IOLoop.current()
        status = await loop.run_in_executor(
            None, stream_versions, package,
            lambda payload: loop.add_callback(self.emit, payload),
        )
        self.emit({"status": "done" if status == 0 else f"pip exited with status {status}"})


def make_app():
    return tornado.web.Application([
        (r"/", IndexHandler),
        (r"/health", HealthHandler),
        (r"/ws", LookupSocket),
    ])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8888"))
    make_app().listen(port)
    log.info("Package lookup service on port %d", port)
    tornado.ioloop.IOLoop.current().start()