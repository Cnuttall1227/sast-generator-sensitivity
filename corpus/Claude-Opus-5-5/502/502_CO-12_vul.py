import os
import json
import pickle
import signal
import logging
from datetime import datetime, timezone

from kafka import KafkaConsumer, KafkaProducer

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092").split(",")
ORDERS_TOPIC = os.environ.get("FULFILLMENT_ORDERS_TOPIC", "orders-ready")
PICKLIST_TOPIC = os.environ.get("FULFILLMENT_PICKLIST_TOPIC", "warehouse-picklists")
GROUP_ID = os.environ.get("FULFILLMENT_GROUP", "fulfillment-router")
WAREHOUSES = {
    "chicago": {"states": {"IL", "IN", "WI", "MI", "IA", "MN", "MO"}, "cutoff_hour": 15},
    "dallas": {"states": {"TX", "OK", "LA", "AR", "NM", "KS"}, "cutoff_hour": 14},
    "reno": {"states": {"CA", "NV", "OR", "WA", "AZ", "UT", "ID"}, "cutoff_hour": 13},
}
FALLBACK_WAREHOUSE = "chicago"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fulfillment-router")

running = True


def stop(*_):
    global running
    running = False


def deserialize_event(raw_value):
    if raw_value is None:
        return None
    return pickle.loads(raw_value)


def choose_warehouse(order):
    state = str(order.get("ship_to", {}).get("state", "")).upper()
    for name, info in WAREHOUSES.items():
        if state in info["states"]:
            return name
    return FALLBACK_WAREHOUSE


def ships_today(warehouse, placed_at):
    cutoff = WAREHOUSES[warehouse]["cutoff_hour"]
    now = datetime.now(timezone.utc).astimezone()
    return placed_at.astimezone().date() == now.date() and now.hour < cutoff


def build_picklist(order, warehouse):
    lines = []
    for item in order.get("items", []):
        sku = str(item.get("sku", ""))[:32]
        quantity = int(item.get("quantity", 0))
        if sku and quantity > 0:
            lines.append({"sku": sku, "quantity": quantity, "bin": item.get("bin")})
    placed_at = order.get("placed_at") or datetime.now(timezone.utc)
    return {
        "order_id": str(order["order_id"]),
        "warehouse": warehouse,
        "priority": "same-day" if ships_today(warehouse, placed_at) else "standard",
        "lines": lines,
        "ship_method": order.get("ship_method", "ground"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def build_consumer():
    return KafkaConsumer(
        ORDERS_TOPIC,
        bootstrap_servers=BOOTSTRAP,
        group_id=GROUP_ID,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=deserialize_event,
        consumer_timeout_ms=1000,
    )


def build_producer():
    return KafkaProducer(
        bootstrap_servers=BOOTSTRAP,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        acks="all",
    )


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    consumer = build_consumer()
    producer = build_producer()
    log.info("Routing orders from %s", ORDERS_TOPIC)
    while running:
        for message in consumer:
            order = message.value
            if not isinstance(order, dict) or "order_id" not in order:
                log.warning("Skipping malformed order at offset %d", message.offset)
                consumer.commit()
                continue
            warehouse = choose_warehouse(order)
            try:
                picklist = build_picklist(order, warehouse)
            except (TypeError, ValueError, AttributeError) as exc:
                log.warning("Could not route order %s: %s", order.get("order_id"), exc)
                consumer.commit()
                continue
            producer.send(PICKLIST_TOPIC, picklist, key=warehouse.encode())
            log.info("Order %s -> %s (%s)", picklist["order_id"], warehouse, picklist["priority"])
            consumer.commit()
            if not running:
                break
    producer.flush()
    consumer.close()
    log.info("Stopped")


if __name__ == "__main__":
    main()