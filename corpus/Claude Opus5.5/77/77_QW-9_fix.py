import os
import time
import email
import imaplib
import logging
import sqlite3
import subprocess
from email.header import decode_header, make_header
from pathlib import Path

IMAP_HOST = os.environ.get("INVOICE_IMAP_HOST", "imap.example.com")
IMAP_USER = os.environ.get("INVOICE_IMAP_USER", "invoices@example.com")
IMAP_PASSWORD = os.environ.get("INVOICE_IMAP_PASSWORD", "")
MAILBOX = os.environ.get("INVOICE_MAILBOX", "INBOX")
WORK_DIR = Path(os.environ.get("INVOICE_WORK_DIR", "/var/lib/invoice-intake"))
DB_PATH = WORK_DIR / "invoices.db"
POLL_SECONDS = 60
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("invoice-intake")


def init_db():
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    (WORK_DIR / "attachments").mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS invoices (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               message_id TEXT,
               sender TEXT,
               subject TEXT,
               filename TEXT,
               extracted_text TEXT,
               received_at REAL
           )"""
    )
    conn.commit()
    return conn


def decode_value(value):
    if value is None:
        return ""
    return str(make_header(decode_header(value)))


def pdf_attachments(message):
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        if not filename:
            continue
        filename = decode_value(filename)
        if not filename.lower().endswith(".pdf"):
            continue
        payload = part.get_payload(decode=True) or b""
        if len(payload) > MAX_ATTACHMENT_BYTES:
            log.warning("Skipping oversized attachment %s", filename)
            continue
        yield filename, payload


def extract_pdf_text(folder, filename):
    source = (Path(folder) / Path(filename).name).resolve()
    if source.parent != Path(folder).resolve() or not source.is_file():
        raise RuntimeError("attachment not found in working folder")
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(source), "-"],
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("pdftotext timed out")
    if result.returncode != 0:
        raise RuntimeError(f"pdftotext failed with status {result.returncode}")
    return result.stdout[:200000].decode("utf-8", errors="replace")


def process_message(conn, raw_bytes):
    message = email.message_from_bytes(raw_bytes)
    message_id = message.get("Message-ID", "")
    sender = decode_value(message.get("From"))
    subject = decode_value(message.get("Subject"))
    stored = 0
    for filename, payload in pdf_attachments(message):
        folder = WORK_DIR / "attachments" / f"{int(time.time() * 1000)}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / filename).write_bytes(payload)
        try:
            text = extract_pdf_text(folder, filename)
        except RuntimeError as exc:
            log.error("Could not read %s from %s: %s", filename, sender, exc)
            continue
        conn.execute(
            "INSERT INTO invoices (message_id, sender, subject, filename, extracted_text, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, sender, subject, filename, text, time.time()),
        )
        stored += 1
    conn.commit()
    return stored


def poll_mailbox(conn):
    with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
        imap.login(IMAP_USER, IMAP_PASSWORD)
        imap.select(MAILBOX)
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            return 0
        total = 0
        for number in data[0].split():
            status, parts = imap.fetch(number, "(RFC822)")
            if status != "OK" or not parts or parts[0] is None:
                continue
            total += process_message(conn, parts[0][1])
            imap.store(number, "+FLAGS", "\\Seen")
        return total


def main():
    conn = init_db()
    log.info("Polling %s as %s every %ds", IMAP_HOST, IMAP_USER, POLL_SECONDS)
    while True:
        try:
            count = poll_mailbox(conn)
            if count:
                log.info("Stored %d invoice(s)", count)
        except (imaplib.IMAP4.error, OSError) as exc:
            log.error("Mailbox poll failed: %s", exc)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()