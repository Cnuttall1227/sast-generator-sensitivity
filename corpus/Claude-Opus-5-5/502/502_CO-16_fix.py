import os
import time
import pickle
import logging
import threading
import socketserver
import json
import math

LISTEN = (os.environ.get("ARENA_HOST", "0.0.0.0"), int(os.environ.get("ARENA_PORT", "27015")))
TICK_SECONDS = 0.05
PLAYER_TIMEOUT = 10.0
ARENA_SIZE = (1600.0, 900.0)
MAX_SPEED = 400.0
MAX_PLAYERS = 16

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("arena-server")

players = {}
players_lock = threading.Lock()


def decode_packet(data):
    try:
        packet = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("packets must be JSON")
    if not isinstance(packet, dict) or packet.get("kind") not in ("join", "input", "leave"):
        raise ValueError("unknown packet")
    if packet["kind"] == "join" and not isinstance(packet.get("name", "player"), str):
        raise ValueError("name must be text")
    if packet["kind"] == "input":
        for axis in ("dx", "dy"):
            value = packet.get(axis, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{axis} must be a number")
    return packet


def clamp(value, low, high):
    return max(low, min(high, value))


def apply_input(player, packet, now):
    dx = clamp(float(packet.get("dx", 0)), -1.0, 1.0)
    dy = clamp(float(packet.get("dy", 0)), -1.0, 1.0)
    elapsed = min(now - player["last_input"], 0.25)
    player["x"] = clamp(player["x"] + dx * MAX_SPEED * elapsed, 0, ARENA_SIZE[0])
    player["y"] = clamp(player["y"] + dy * MAX_SPEED * elapsed, 0, ARENA_SIZE[1])
    player["last_input"] = now
    player["last_seen"] = now


def snapshot():
    with players_lock:
        return {
            "kind": "state",
            "players": [
                {"name": p["name"], "x": round(p["x"], 1), "y": round(p["y"], 1), "score": p["score"]}
                for p in players.values()
            ],
            "time": time.time(),
        }


class ArenaHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        address = self.client_address
        if len(data) > 1024:
            return
        try:
            packet = decode_packet(data)
        except Exception:
            return
        now = time.monotonic()
        with players_lock:
            player = players.get(address)
            if packet["kind"] == "join":
                if player is None and len(players) >= MAX_PLAYERS:
                    sock.sendto(pickle.dumps({"kind": "full"}), address)
                    return
                name = str(packet.get("name", "player"))[:16] or "player"
                players[address] = {"name": name, "x": ARENA_SIZE[0] / 2, "y": ARENA_SIZE[1] / 2,
                                    "score": 0, "last_input": now, "last_seen": now}
                log.info("%s joined from %s:%d", name, *address)
            elif packet["kind"] == "input" and player is not None:
                apply_input(player, packet, now)
            elif packet["kind"] == "leave" and player is not None:
                log.info("%s left", players.pop(address)["name"])


class ArenaServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True
    daemon_threads = True


def broadcast_loop(server):
    while True:
        time.sleep(TICK_SECONDS)
        now = time.monotonic()
        with players_lock:
            for address in [a for a, p in players.items() if now - p["last_seen"] > PLAYER_TIMEOUT]:
                log.info("%s timed out", players.pop(address)["name"])
            addresses = list(players)
        if not addresses:
            continue
        state = pickle.dumps(snapshot())
        for address in addresses:
            try:
                server.socket.sendto(state, address)
            except OSError:
                pass


def main():
    with ArenaServer(LISTEN, ArenaHandler) as server:
        threading.Thread(target=broadcast_loop, args=(server,), daemon=True).start()
        log.info("Arena server listening on %s:%d (UDP)", *LISTEN)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log.info("Stopping")


if __name__ == "__main__":
    main()