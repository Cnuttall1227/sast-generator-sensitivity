import os
import json
import time
import logging
import threading
from collections import deque
from multiprocessing.connection import Listener
from pathlib import Path

LISTEN_ADDRESS = (os.environ.get("RENDER_HOST", "0.0.0.0"), int(os.environ.get("RENDER_PORT", "6001")))
QUEUE_FILE = Path(os.environ.get("RENDER_QUEUE", "/srv/renderfarm/queue.json"))
RESULTS_DIR = Path(os.environ.get("RENDER_RESULTS", "/srv/renderfarm/results"))
LEASE_SECONDS = 600

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("render-dispatcher")

pending = deque()
leased = {}
completed = []
state_lock = threading.Lock()


def load_queue():
    if QUEUE_FILE.exists():
        for job in json.loads(QUEUE_FILE.read_text(encoding="utf-8")):
            pending.append(job)
    log.info("Loaded %d pending frame(s)", len(pending))


def reclaim_expired_leases():
    now = time.monotonic()
    with state_lock:
        for frame_id, (job, worker, leased_at) in list(leased.items()):
            if now - leased_at > LEASE_SECONDS:
                log.warning("Lease on %s by %s expired; requeueing", frame_id, worker)
                pending.appendleft(job)
                del leased[frame_id]


def next_job(worker):
    reclaim_expired_leases()
    with state_lock:
        if not pending:
            return None
        job = pending.popleft()
        leased[job["frame_id"]] = (job, worker, time.monotonic())
        return job


def record_result(worker, frame_id, seconds, output_name):
    with state_lock:
        entry = leased.pop(frame_id, None)
        if entry is None:
            return False
        completed.append({"frame_id": frame_id, "worker": worker, "seconds": seconds, "output": output_name})
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "completed.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(completed[-1]) + "\n")
    return True


def handle_worker(conn, address):
    worker = f"{address[0]}:{address[1]}"
    log.info("Worker connected from %s", worker)
    try:
        while True:
            message = conn.recv()
            if not isinstance(message, dict):
                conn.send({"type": "error", "reason": "messages must be dicts"})
                continue
            kind = message.get("type")
            if kind == "hello":
                worker = str(message.get("name", worker))[:64]
                conn.send({"type": "welcome", "lease_seconds": LEASE_SECONDS})
            elif kind == "request":
                job = next_job(worker)
                conn.send({"type": "job", "job": job} if job else {"type": "idle", "retry_in": 30})
            elif kind == "result":
                ok = record_result(worker, str(message.get("frame_id")), float(message.get("seconds", 0)),
                                   str(message.get("output", ""))[:200])
                conn.send({"type": "ack" if ok else "unknown_frame"})
            elif kind == "bye":
                break
            else:
                conn.send({"type": "error", "reason": f"unknown message type {kind!r}"})
    except (EOFError, ConnectionResetError):
        pass
    finally:
        conn.close()
        log.info("Worker %s disconnected", worker)


def status_reporter():
    while True:
        time.sleep(60)
        with state_lock:
            log.info("Pending %d, leased %d, completed %d", len(pending), len(leased), len(completed))


def main():
    load_queue()
    threading.Thread(target=status_reporter, daemon=True).start()
    with Listener(LISTEN_ADDRESS) as listener:
        log.info("Render dispatcher listening on %s:%d", *LISTEN_ADDRESS)
        while True:
            conn = listener.accept()
            threading.Thread(target=handle_worker, args=(conn, listener.last_accepted), daemon=True).start()


if __name__ == "__main__":
    main()