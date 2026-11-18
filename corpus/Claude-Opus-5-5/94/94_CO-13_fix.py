import os
import json
import hmac
import ast
import logging
import threading
import socketserver
from datetime import datetime, timezone

LISTEN_HOST = os.environ.get("KVSTORE_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("KVSTORE_PORT", "7311"))
AUTH_TOKEN = os.environ.get("KVSTORE_TOKEN", "")
DATA_FILE = os.environ.get("KVSTORE_FILE", "/var/lib/kiosk-kv/store.json")
MAX_LINE = 4096
MAX_KEYS = 5000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kiosk-kv")

store = {}
store_lock = threading.Lock()


def load_store():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as handle:
            store.update(json.load(handle))
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def persist():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(store, handle)
    os.replace(tmp, DATA_FILE)


def parse_value(raw):
    raw = raw.strip()
    if not raw:
        raise ValueError("missing value")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = ast.literal_eval(raw)
    if not isinstance(value, (str, int, float, bool, list, dict, type(None))):
        raise ValueError("values must be strings, numbers, booleans, lists, dicts or null")
    json.dumps(value)
    return value


def valid_key(key):
    return 0 < len(key) <= 128 and all(ch.isalnum() or ch in "._-/" for ch in key)


class KioskKVHandler(socketserver.StreamRequestHandler):
    timeout = 120

    def reply(self, text):
        self.wfile.write((text + "\r\n").encode("utf-8"))

    def handle(self):
        client = f"{self.client_address[0]}:{self.client_address[1]}"
        authed = False
        self.reply("KIOSK-KV READY")
        while True:
            raw = self.rfile.readline(MAX_LINE + 1)
            if not raw:
                break
            if len(raw) > MAX_LINE:
                self.reply("ERR line too long")
                break
            line = raw.decode("utf-8", errors="replace").strip()
            command, _, rest = line.partition(" ")
            command = command.upper()
            if command == "AUTH":
                authed = bool(AUTH_TOKEN) and hmac.compare_digest(rest.strip(), AUTH_TOKEN)
                self.reply("OK" if authed else "ERR bad token")
                continue
            if command == "QUIT":
                self.reply("BYE")
                break
            if command == "PING":
                self.reply("PONG")
                continue
            if not authed:
                self.reply("ERR AUTH first")
                continue
            if command == "GET":
                key = rest.strip()
                with store_lock:
                    present = key in store
                    value = store.get(key)
                self.reply(f"VALUE {json.dumps(value)}" if present else "NOTFOUND")
            elif command == "SET":
                key, _, raw_value = rest.partition(" ")
                if not valid_key(key):
                    self.reply("ERR invalid key")
                    continue
                try:
                    value = parse_value(raw_value)
                except (ValueError, SyntaxError, TypeError, NameError) as exc:
                    self.reply(f"ERR {type(exc).__name__}")
                    continue
                with store_lock:
                    if key not in store and len(store) >= MAX_KEYS:
                        self.reply("ERR store full")
                        continue
                    store[key] = value
                    persist()
                log.info("%s set %s", client, key)
                self.reply("OK")
            elif command == "DEL":
                with store_lock:
                    removed = store.pop(rest.strip(), None) is not None
                    if removed:
                        persist()
                self.reply("OK" if removed else "NOTFOUND")
            elif command == "KEYS":
                prefix = rest.strip()
                with store_lock:
                    keys = sorted(k for k in store if k.startswith(prefix))[:500]
                self.reply("KEYS " + json.dumps(keys))
            elif command == "STAMP":
                self.reply("TIME " + datetime.now(timezone.utc).isoformat())
            else:
                self.reply("ERR unknown command")


class ThreadedServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    if not AUTH_TOKEN:
        raise SystemExit("Set KVSTORE_TOKEN before starting")
    load_store()
    with ThreadedServer((LISTEN_HOST, LISTEN_PORT), KioskKVHandler) as server:
        log.info("Kiosk KV store on %s:%d with %d key(s)", LISTEN_HOST, LISTEN_PORT, len(store))
        server.serve_forever()