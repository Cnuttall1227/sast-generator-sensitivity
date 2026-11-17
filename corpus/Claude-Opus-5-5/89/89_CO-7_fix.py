import os
import json
import sqlite3
import logging
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

BROKER_HOST = os.environ.get("TELEMETRY_BROKER", "localhost")
BROKER_PORT = int(os.environ.get("TELEMETRY_BROKER_PORT", "1883"))
TOPIC_FILTER = os.environ.get("TELEMETRY_TOPIC", "greenhouse/+/readings")
DB_PATH = os.environ.get("TELEMETRY_DB", "/var/lib/greenhouse/telemetry.db")
MQTT_USER = os.environ.get("TELEMETRY_MQTT_USER")
MQTT_PASSWORD = os.environ.get("TELEMETRY_MQTT_PASSWORD")
ALERT_TOPIC = "greenhouse/alerts"
LIMITS = {"temperature_c": (5.0, 38.0), "humidity_pct": (30.0, 95.0), "soil_moisture_pct": (20.0, 80.0)}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("telemetry-recorder")

db_lock = threading.Lock()
conn = sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with db_lock, conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS readings (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   device_id TEXT NOT NULL,
                   recorded_at TEXT NOT NULL,
                   temperature_c REAL,
                   humidity_pct REAL,
                   soil_moisture_pct REAL)"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_device ON readings (device_id, recorded_at)")


def device_from_topic(topic):
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "greenhouse" or parts[2] != "readings" or not parts[1]:
        return None
    return parts[1]


def parse_number(payload, key):
    value = payload.get(key)
    if value is None:
        return None
    number = float(value)
    if number != number or abs(number) > 1e6:
        raise ValueError(f"{key} out of range")
    return number


def store_reading(device_id, reading):
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sql = (
        "INSERT INTO readings (device_id, recorded_at, temperature_c, humidity_pct, soil_moisture_pct) "
        "VALUES (?, ?, ?, ?, ?)"
    )
    params = (
        str(device_id)[:64],
        recorded_at,
        reading.get("temperature_c"),
        reading.get("humidity_pct"),
        reading.get("soil_moisture_pct"),
    )
    with db_lock, conn:
        conn.execute(sql, params)
    return recorded_at


def out_of_range(reading):
    problems = []
    for key, (low, high) in LIMITS.items():
        value = reading.get(key)
        if value is not None and not low <= value <= high:
            problems.append(f"{key}={value:g} (expected {low:g}–{high:g})")
    return problems


def on_connect(client, userdata, flags, reason_code, properties=None):
    log.info("Connected to broker (%s), subscribing to %s", reason_code, TOPIC_FILTER)
    client.subscribe(TOPIC_FILTER, qos=1)


def on_message(client, userdata, message):
    device_id = device_from_topic(message.topic)
    if device_id is None:
        return
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        reading = {key: parse_number(payload, key) for key in LIMITS}
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("Bad reading from %s: %s", device_id, exc)
        return
    if all(v is None for v in reading.values()):
        return
    recorded_at = store_reading(device_id, reading)
    problems = out_of_range(reading)
    if problems:
        alert = {"device": device_id, "at": recorded_at, "problems": problems}
        client.publish(ALERT_TOPIC, json.dumps(alert), qos=1)
        log.warning("Alert for %s: %s", device_id, "; ".join(problems))


def prune_old_readings(days=90):
    with db_lock, conn:
        removed = conn.execute(
            "DELETE FROM readings WHERE recorded_at < datetime('now', ?)", (f"-{int(days)} days",)
        ).rowcount
    if removed:
        log.info("Pruned %d old reading(s)", removed)


def main():
    init_db()
    prune_old_readings()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="telemetry-recorder")
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