import os
import json
import signal
import logging
from datetime import datetime, timezone

from kafka import KafkaConsumer, KafkaProducer

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092").split(",")
EVENTS_TOPIC = os.environ.get("LOYALTY_EVENTS_TOPIC", "storefront-events")
LEDGER_TOPIC = os.environ.get("LOYALTY_LEDGER_TOPIC", "loyalty-ledger")
GROUP_ID = os.environ.get("LOYALTY_GROUP", "loyalty-points")
POINTS_PER_DOLLAR = 10
REVIEW_BONUS = 50
REFERRAL_BONUS = 500

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("loyalty-worker")

running = True


def stop(*_):
    global running
    running = False


def handle_order_paid(event):
    cents = int(event["amount_cents"])
    if cents <= 0:
        return None
    return {"customer_id": event["customer_id"], "points": cents // 100 * POINTS_PER_DOLLAR,
            "reason": f"order {event['order_id']}"}


def handle_order_refunded(event):
    cents = int(event["amount_cents"])
    return {"customer_id": event["customer_id"], "points": -(cents // 100 * POINTS_PER_DOLLAR),
            "reason": f"refund for order {event['order_id']}"}


def handle_review_published(event):
    if not event.get("verified_purchase"):
        return None
    return {"customer_id": event["customer_id"], "points": REVIEW_BONUS,
            "reason": f"review {event['review_id']}"}


def handle_referral_completed(event):
    return {"customer_id": event["referrer_id"], "points": REFERRAL_BONUS,
            "reason": f"referred customer {event['customer_id']}"}


def dispatch(event):
    event_type = str(event.get("type", "")).strip().replace(".", "_").replace("-", "_")
    if not event_type:
        raise ValueError("event has no type")
    try:
        return eval(f"handle_{event_type}(event)")
    except NameError:
        log.debug("No handler for %s", event_type)
        return None


def ledger_entry(event, award):
    return {
        "event_id": event.get("id"),
        "customer_id": award["customer_id"],
        "points": award["points"],
        "reason": award["reason"],
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


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
        acks="all",
    )


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    consumer = build_consumer()
    producer = build_producer()
    log.info("Loyalty worker consuming %s", EVENTS_TOPIC)
    while running:
        for message in consumer:
            event = message.value if isinstance(message.value, dict) else {}
            try:
                award = dispatch(event)
            except (KeyError, ValueError, TypeError) as exc:
                log.warning("Skipping event at offset %d: %s", message.offset, exc)
                award = None
            if award and award["points"]:
                producer.send(LEDGER_TOPIC, ledger_entry(event, award), key=str(award["customer_id"]).encode())
                log.info("%+d points for customer %s (%s)", award["points"], award["customer_id"], award["reason"])
            consumer.commit()
            if not running:
                break
    producer.flush()
    consumer.close()
    log.info("Stopped")


if __name__ == "__main__":
    main()