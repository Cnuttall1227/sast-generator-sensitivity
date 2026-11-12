import os
import json
import hmac
import time
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SPOOL_DIR = os.environ.get("SPOOL_DIR", "/var/spool/printshop")
API_TOKEN = os.environ.get("SPOOL_TOKEN", "change-me")
MAX_BODY = 64 * 1024
STALE_SECONDS = 7 * 24 * 3600

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("spool-admin")


def spool_entries():
    entries = []
    for queue in sorted(os.listdir(SPOOL_DIR)):
        queue_dir = os.path.join(SPOOL_DIR, queue)
        if not os.path.isdir(queue_dir):
            continue
        for job in sorted(os.listdir(queue_dir)):
            job_path = os.path.join(queue_dir, job)
            if os.path.isfile(job_path):
                stat = os.stat(job_path)
                entries.append({
                    "queue": queue,
                    "job": job,
                    "bytes": stat.st_size,
                    "age_seconds": int(time.time() - stat.st_mtime),
                })
    return entries


def is_plain_name(value):
    return (
        bool(value)
        and value not in (".", "..")
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
        and len(value) <= 255
    )


def cancel_job(queue, job):
    if not is_plain_name(queue) or not is_plain_name(job):
        return False
    root = os.path.realpath(SPOOL_DIR)
    queue_dir = os.path.realpath(os.path.join(root, queue))
    if os.path.dirname(queue_dir) != root or not os.path.isdir(queue_dir):
        return False
    job_path = os.path.join(queue_dir, job)
    if os.path.islink(job_path) or not os.path.isfile(job_path):
        return False
    os.remove(job_path)
    log.info("Cancelled job %s in queue %s", job, queue)
    return True


def purge_stale(max_age):
    removed = 0
    for entry in spool_entries():
        if entry["age_seconds"] > max_age:
            os.remove(os.path.join(SPOOL_DIR, entry["queue"], entry["job"]))
            removed += 1
    return removed


class SpoolHandler(BaseHTTPRequestHandler):
    server_version = "SpoolAdmin/1.0"

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, f"Bearer {API_TOKEN}")

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return None

    def do_GET(self):
        if self.path == "/health":
            self.send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if not self.authorized():
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if self.path == "/jobs":
            self.send_json(HTTPStatus.OK, {"jobs": spool_entries()})
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self):
        if not self.authorized():
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        payload = self.read_json()
        if payload is None:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON body"})
            return
        if self.path == "/jobs/cancel":
            queue = str(payload.get("queue", ""))
            job = str(payload.get("job", ""))
            if not queue or not job:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "queue and job are required"})
                return
            if cancel_job(queue, job):
                self.send_json(HTTPStatus.OK, {"cancelled": job})
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "no such job"})
            return
        if self.path == "/jobs/purge":
            max_age = int(payload.get("max_age_seconds", STALE_SECONDS))
            self.send_json(HTTPStatus.OK, {"removed": purge_stale(max(3600, max_age))})
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


if __name__ == "__main__":
    os.makedirs(SPOOL_DIR, exist_ok=True)
    port = int(os.environ.get("PORT", "8631"))
    server = ThreadingHTTPServer(("0.0.0.0", port), SpoolHandler)
    log.info("Spool admin listening on port %d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()