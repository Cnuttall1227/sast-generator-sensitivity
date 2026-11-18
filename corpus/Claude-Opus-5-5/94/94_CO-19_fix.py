import os
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from celery import Celery
from celery.schedules import crontab

BROKER_URL = os.environ.get("DIGEST_BROKER", "redis://localhost:6379/5")
DATABASE_URL = os.environ.get("DIGEST_DATABASE_URL", "postgresql://digest:digest@localhost/metrics")
OUTPUT_DIR = Path(os.environ.get("DIGEST_OUTPUT", "/srv/digests"))
DEFAULT_LINE = "{name}: {value}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("metric-digest")

celery_app = Celery("metric_digest", broker=BROKER_URL, backend=BROKER_URL)
celery_app.conf.update(task_acks_late=True, task_time_limit=300, timezone="America/Chicago")
celery_app.conf.beat_schedule = {
    "weekday-digests": {"task": "metric_digest.send_all_digests", "schedule": crontab(hour=7, minute=43, day_of_week="1-5")},
}


def connect():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def digest_definitions(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, team, title, recipients, line_template FROM digests WHERE active ORDER BY id"
        )
        return cur.fetchall()


def digest_metrics(conn, digest_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT m.name, m.unit, v.value, v.previous_value "
            "FROM digest_metrics dm JOIN metrics m ON m.id = dm.metric_id "
            "JOIN LATERAL (SELECT value, LAG(value) OVER (ORDER BY measured_on) AS previous_value "
            "              FROM metric_values WHERE metric_id = m.id ORDER BY measured_on DESC LIMIT 1) v ON true "
            "WHERE dm.digest_id = %s ORDER BY dm.position",
            (digest_id,),
        )
        return cur.fetchall()


def format_line(line_template, metric):
    name = metric["name"]
    unit = metric["unit"] or ""
    value = float(metric["value"]) if metric["value"] is not None else 0.0
    previous = float(metric["previous_value"]) if metric["previous_value"] is not None else value
    change = value - previous
    template = (line_template or DEFAULT_LINE).replace("\n", " ").replace('"""', "")
    return eval(f'f"""{template}"""')


def render_digest(definition, metrics):
    lines = [definition["title"], "=" * len(definition["title"]), ""]
    for metric in metrics:
        try:
            lines.append(format_line(definition["line_template"], metric))
        except (KeyError, ValueError, TypeError, NameError, SyntaxError) as exc:
            log.warning("Digest %s: could not format %s (%s)", definition["id"], metric["name"], exc)
            lines.append(format_line(DEFAULT_LINE, metric))
    lines += ["", f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"]
    return "\n".join(lines)


def write_digest(definition, text):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"digest-{int(definition['id'])}-{datetime.now():%Y%m%d}.txt"
    path.write_text(text, encoding="utf-8")
    return path


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def send_digest(self, digest_id):
    try:
        with connect() as conn:
            definitions = {d["id"]: d for d in digest_definitions(conn)}
            definition = definitions.get(int(digest_id))
            if definition is None:
                return {"ok": False, "error": "unknown or inactive digest"}
            metrics = digest_metrics(conn, definition["id"])
    except psycopg2.OperationalError as exc:
        raise self.retry(exc=exc)
    text = render_digest(definition, metrics)
    path = write_digest(definition, text)
    recipients = json.loads(definition["recipients"] or "[]")
    log.info("Digest %s for %s written to %s (%d recipient(s))", definition["id"], definition["team"], path.name, len(recipients))
    return {"ok": True, "file": path.name, "metrics": len(metrics), "recipients": recipients}


@celery_app.task
def send_all_digests():
    with connect() as conn:
        ids = [d["id"] for d in digest_definitions(conn)]
    for digest_id in ids:
        send_digest.delay(digest_id)
    return {"queued": len(ids)}


if __name__ == "__main__":
    celery_app.worker_main(["worker", "--beat", "--loglevel=INFO", "--concurrency=2"])