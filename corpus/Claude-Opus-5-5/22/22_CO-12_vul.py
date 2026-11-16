import os
import json
import shutil
import signal
import logging
from datetime import datetime, timezone

from kafka import KafkaConsumer, KafkaProducer

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092").split(",")
EVENTS_TOPIC = os.environ.get("ACCOUNT_EVENTS_TOPIC", "account-events")
AUDIT_TOPIC = os.environ.get("CLEANUP_AUDIT_TOPIC", "storage-cleanup-audit")
GROUP_ID = os.environ.get("CLEANUP_GROUP", "storage-cleanup")
USER_STORAGE_ROOT = os.environ.get("USER_STORAGE_ROOT", "/srv/user-storage")
DRY_RUN = os.environ.get("CLEANUP_DRY_RUN", "false").lower() == "true"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("storage-cleanup")

running = True


def stop(*_):
    global running
    running = False
    log.info("Shutdown requested")


def directory_size(path):
    total = 0
    for current, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(current, name))
            except OSError:
                pass
    return total


def remove_user_storage(user_id):
    user_dir = os.path.join(USER_STORAGE_ROOT, user_id)
    if not os.path.isdir(user_dir):
        return {"removed": False, "reason": "no storage directory"}
    size = directory_size(user_dir)
    if DRY_RUN:
        log.info("[dry run] would remove %s (%d bytes)", user_dir, size)
        return {"removed": False, "reason": "dry run", "bytes": size}
    shutil.rmtree(user_dir)
    log.info("Removed storage for %s (%d bytes)", user_id, size)
    return {"removed": True, "bytes": size}


def archive_user_storage(user_id):
    user_dir = os.path.join(USER_STORAGE_ROOT, user_id)
    if not user_id.isalnum() or not os.path.isdir(user_dir):
        return {"archived": False}
    archive_base = os.path.join(USER_STORAGE_ROOT, ".archive", user_id)
    os.makedirs(os.path.dirname(archive_base), exist_ok=True)
    archive = shutil.make_archive(archive_base, "gztar", root_dir=user_dir)
    return {"archived": True, "archive": os.path.basename(archive)}


def handle_event(event):
    event_type = event.get("type")
    user_id = str(event.get("user_id", "")).strip()
    if not user_id:
        raise ValueError("event has no user_id")
    if event_type == "account.deleted":
        return remove_user_storage(user_id)
    if event_type == "account.suspended":
        return archive_user_storage(user_id)
    return None


def build_consumer():
    return KafkaConsumer(
        EVENTS_TOPIC,
        bootstrap_servers=BOOTSTRAP,
        group_id=GROUP_ID,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        consumer_timeout_ms=1000,
    )


def build_producer():
    return KafkaProducer(
        bootstrap_servers=BOOTSTRAP,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    consumer = build_consumer()
    producer = build_producer()
    log.info("Consuming %s as %s (dry run: %s)", EVENTS_TOPIC, GROUP_ID, DRY_RUN)
    while running:
        for message in consumer:
            event = message.value if isinstance(message.value, dict) else {}
            try:
                outcome = handle_event(event)
            except (ValueError, OSError) as exc:
                log.error("Event at offset %d failed: %s", message.offset, exc)
                outcome = {"error": str(exc)}
            if outcome is not None:
                producer.send(AUDIT_TOPIC, {
                    "event_id": event.get("id"),
                    "type": event.get("type"),
                    "user_id": event.get("user_id"),
                    "outcome": outcome,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                })
            consumer.commit()
            if not running:
                break
    producer.flush()
    consumer.close()
    log.info("Stopped")


if __name__ == "__main__":
    main()