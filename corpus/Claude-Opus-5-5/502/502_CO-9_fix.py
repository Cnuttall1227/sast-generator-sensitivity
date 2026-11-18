import os
import json
import pickle
import sqlite3
import logging
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

BROKER_HOST = os.environ.get("EDGE_BROKER", "localhost")
BROKER_PORT = int(os.environ.get("EDGE_BROKER_PORT", "1883"))
MQTT_USER = os.environ.get("EDGE_MQTT_USER")
MQTT_PASSWORD = os.environ.get("EDGE_MQTT_PASSWORD")
BATCH_TOPIC = "factory/+/batches"
SUMMARY_TOPIC = "factory/summary"
DB_PATH = os.environ.get("EDGE_DB", "/var/lib/edge-gateway/readings.db")
MAX_BATCH = 5000
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("edge-gateway")

db_lock = threading.Lock()
conn = sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with db_lock, conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS readings (
                   line TEXT NOT NULL, sensor TEXT NOT NULL, taken_at TEXT NOT NULL,
                   value REAL NOT NULL, unit TEXT)"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_line_time ON readings (line, taken_at)")


def decode_batch(payload):
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("batch is too large")
    batch = json.loads(payload.decode("utf-8"))
    if not isinstance(batch, dict) or not isinstance(batch.get("readings"), list):
        raise ValueError("batch must be a JSON object with a readings list")
    for reading in batch["readings"][:MAX_BATCH]:
        if isinstance(reading, dict) and isinstance(reading.get("taken_at"), str):
            try:
                taken_at = datetime.fromisoformat(reading["taken_at"].replace("Z", "+00:00"))
            except ValueError:
                reading.pop("taken_at")
                continue
            if taken_at.tzinfo is None:
                taken_at = taken_at.replace(tzinfo=timezone.utc)
            reading["taken_at"] = taken_at
    return batch

def validate_readings(readings):
    clean = []
    for reading in readings[:MAX_BATCH]:
        try:
            sensor = str(reading["sensor"])[:40]
            taken_at = reading["taken_at"]
            if isinstance(taken_at, (int, float)):
                taken_at = datetime.fromtimestamp(taken_at, timezone.utc)
            value = float(reading["value"])
        except (KeyError, TypeError, ValueError, OSError):
            continue
        if value != value:
            continue
        clean.append((sensor, taken_at.isoformat(), value, str(reading.get("unit", ""))[:10]))
    return clean


def store(line, rows):
    with db_lock, conn:
        conn.executemany(
            "INSERT INTO readings (line, sensor, taken_at, value, unit) VALUES (?, ?, ?, ?, ?)",
            [(line, *row) for row in rows],
        )


def line_summary(line):
    with db_lock:
        rows = conn.execute(
            "SELECT sensor, COUNT(*), AVG(value), MIN(value), MAX(value) FROM readings "
            "WHERE line = ? AND taken_at >= datetime('now', '-1 hour') GROUP BY sensor",
            (line,),
        ).fetchall()
    return {sensor: {"count": n, "avg": round(avg, 3), "min": lo, "max": hi} for sensor, n, avg, lo, hi in rows}


def on_connect(client, userdata, flags, reason_code, properties=None):
    log.info("Connected to broker (%s)", reason_code)
    client.subscribe(BATCH_TOPIC, qos=1)


def on_message(client, userdata, message):
    parts = message.topic.split("/")
    line = parts[1] if len(parts) == 3 else ""
    if not line.replace("-", "").isalnum():
        return
    try:
        batch = decode_batch(message.payload)
    except Exception as exc:
        log.warning("Rejected batch from %s: %s", line, exc)
        return
    rows = validate_readings(batch["readings"])
    if not rows:
        return
    store(line, rows)
    summary = {"line": line, "stored": len(rows), "last_hour": line_summary(line),
               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    client.publish(SUMMARY_TOPIC, json.dumps(summary), qos=0)
    log.info("Stored %d reading(s) from %s", len(rows), line)


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edge-gateway")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        log.info("Stopping")
    finally:
        client.disconnect()
        conn.close()


if __name__ == "__main__":
    main()