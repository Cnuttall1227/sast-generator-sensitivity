import os
import json
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone

from celery import Celery
from kombu import Queue

BROKER_URL = os.environ.get("MAILER_BROKER", "redis://mail-broker.internal:6379/0")
RESULT_BACKEND = os.environ.get("MAILER_RESULTS", "redis://mail-broker.internal:6379/1")
SMTP_HOST = os.environ.get("MAILER_SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("MAILER_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("MAILER_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("MAILER_SMTP_PASSWORD", "")
FROM_ADDRESS = os.environ.get("MAILER_FROM", "Notifications <no-reply@example.com>")
MAX_RECIPIENTS = 50
LOG_FILE = os.environ.get("MAILER_LOG", "/var/log/mailer/sent.jsonl")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mailer-worker")


def make_celery():
    app = Celery("mailer", broker=BROKER_URL, backend=RESULT_BACKEND)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_accept_content=["json"],
        task_acks_late=True,
        worker_prefetch_multiplier=4,
        task_time_limit=60,
        task_queues=(Queue("mail", routing_key="mail"), Queue("mail-bulk", routing_key="mail-bulk")),
        task_default_queue="mail",
        timezone="UTC",
    )
    return app


celery_app = make_celery()


def valid_address(address):
    address = str(address).strip()
    local, _, domain = address.partition("@")
    return bool(local) and "." in domain and " " not in address and len(address) <= 254


def build_message(to, subject, text_body, html_body=None, reply_to=None):
    message = EmailMessage()
    message["From"] = FROM_ADDRESS
    message["To"] = ", ".join(to)
    message["Subject"] = subject.replace("\r", " ").replace("\n", " ")[:200]
    if reply_to and valid_address(reply_to):
        message["Reply-To"] = reply_to
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    return message


def record(entry):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


@celery_app.task(bind=True, max_retries=5, default_retry_delay=30)
def send_email(self, to, subject, text_body, html_body=None, reply_to=None, tags=None):
    recipients = [str(a).strip() for a in (to if isinstance(to, list) else [to]) if valid_address(a)]
    if not recipients:
        return {"ok": False, "error": "no valid recipients"}
    if len(recipients) > MAX_RECIPIENTS:
        return {"ok": False, "error": f"at most {MAX_RECIPIENTS} recipients per message"}
    message = build_message(recipients, str(subject), str(text_body), html_body, reply_to)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            if SMTP_USER:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(message)
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, TimeoutError, OSError) as exc:
        raise self.retry(exc=exc)
    entry = {"to": recipients, "subject": message["Subject"], "tags": list(tags or [])[:10],
             "sent_at": datetime.now(timezone.utc).isoformat()}
    record(entry)
    log.info("Sent '%s' to %d recipient(s)", entry["subject"], len(recipients))
    return {"ok": True, **entry}


@celery_app.task
def send_digest(user_email, items):
    lines = [f"- {str(item.get('title', ''))[:120]}" for item in items[:25] if isinstance(item, dict)]
    if not lines:
        return {"ok": False, "error": "nothing to send"}
    body = "Here's what happened while you were away:\n\n" + "\n".join(lines)
    return send_email.apply_async(args=([user_email], "Your daily digest", body), queue="mail-bulk").id


if __name__ == "__main__":
    celery_app.worker_main(["worker", "--loglevel=INFO", "--queues=mail,mail-bulk", "--concurrency=4"])