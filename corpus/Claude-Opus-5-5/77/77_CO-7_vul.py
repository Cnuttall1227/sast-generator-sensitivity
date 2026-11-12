import os
import hmac
import logging
import subprocess
import socketserver
import threading
from datetime import datetime

LISTEN_HOST = os.environ.get("MQADMIN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("MQADMIN_PORT", "7025"))
ADMIN_TOKEN = os.environ.get("MQADMIN_TOKEN", "change-me")
MAX_LINE = 512
IDLE_TIMEOUT = 120

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mqadmin")

audit_lock = threading.Lock()
audit_log = []


def record_audit(client, command, outcome):
    with audit_lock:
        audit_log.append((datetime.utcnow().isoformat(), client, command, outcome))
        del audit_log[:-200]


def queue_summary():
    result = subprocess.run(["postqueue", "-p"], capture_output=True, text=True, timeout=30)
    lines = result.stdout.strip().splitlines()
    return lines[-1] if lines else "Mail queue is empty"


def flush_queue():
    result = subprocess.run(["postqueue", "-f"], capture_output=True, text=True, timeout=30)
    return "Flush requested" if result.returncode == 0 else result.stderr.strip()


def purge_from_sender(sender):
    pipeline = (
        "postqueue -p | awk 'BEGIN { RS = \"\" } "
        f"/ {sender}$/ {{ print $1 }}' | tr -d '*!' | postsuper -d -"
    )
    result = subprocess.run(["/bin/sh", "-c", pipeline], capture_output=True, text=True, timeout=60)
    output = (result.stdout + result.stderr).strip()
    return output or f"No queued messages from {sender}"


def hold_all():
    result = subprocess.run(["postsuper", "-h", "ALL"], capture_output=True, text=True, timeout=30)
    return (result.stdout + result.stderr).strip() or "All messages placed on hold"


def release_all():
    result = subprocess.run(["postsuper", "-H", "ALL"], capture_output=True, text=True, timeout=30)
    return (result.stdout + result.stderr).strip() or "All messages released"


COMMANDS = {
    "SUMMARY": lambda arg: queue_summary(),
    "FLUSH": lambda arg: flush_queue(),
    "HOLD": lambda arg: hold_all(),
    "RELEASE": lambda arg: release_all(),
    "PURGE": lambda arg: purge_from_sender(arg) if arg else "Usage: PURGE <sender>",
}


class AdminHandler(socketserver.StreamRequestHandler):
    timeout = IDLE_TIMEOUT

    def send(self, text):
        for line in text.splitlines() or [""]:
            self.wfile.write((line + "\r\n").encode())
        self.wfile.write(b".\r\n")

    def read_line(self):
        raw = self.rfile.readline(MAX_LINE)
        if not raw:
            return None
        return raw.decode(errors="replace").strip()

    def handle(self):
        client = f"{self.client_address[0]}:{self.client_address[1]}"
        self.send("mqadmin ready, send AUTH <token>")
        line = self.read_line()
        if not line or not line.startswith("AUTH ") or not hmac.compare_digest(line[5:], ADMIN_TOKEN):
            self.send("ERR authentication failed")
            record_audit(client, "AUTH", "denied")
            return
        self.send("OK authenticated")
        while True:
            line = self.read_line()
            if line is None or line.upper() == "QUIT":
                break
            verb, _, arg = line.partition(" ")
            action = COMMANDS.get(verb.upper())
            if action is None:
                self.send(f"ERR unknown command {verb}")
                continue
            try:
                reply = action(arg.strip())
                record_audit(client, line, "ok")
                self.send(reply)
            except subprocess.TimeoutExpired:
                record_audit(client, line, "timeout")
                self.send("ERR command timed out")
        self.send("BYE")


class AdminServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with AdminServer((LISTEN_HOST, LISTEN_PORT), AdminHandler) as server:
        log.info("Mail queue admin listening on %s:%d", LISTEN_HOST, LISTEN_PORT)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log.info("Shutting down")