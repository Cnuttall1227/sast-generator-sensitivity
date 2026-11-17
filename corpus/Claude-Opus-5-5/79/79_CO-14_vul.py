import os
import email
import imaplib
import logging
from datetime import datetime
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from html import escape

import uvicorn
from litestar import Litestar, get
from litestar.exceptions import NotFoundException
from litestar.response import Response

IMAP_HOST = os.environ.get("HELPDESK_IMAP_HOST", "imap.example.com")
IMAP_USER = os.environ.get("HELPDESK_IMAP_USER", "help@example.com")
IMAP_PASSWORD = os.environ.get("HELPDESK_IMAP_PASSWORD", "")
MAILBOX = os.environ.get("HELPDESK_MAILBOX", "INBOX")
MAX_MESSAGES = 50

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("helpdesk-inbox")

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:sans-serif;margin:2rem}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:.4rem;border-bottom:1px solid #eee;text-align:left}}.unread{{font-weight:bold}}
pre{{white-space:pre-wrap;background:#fafafa;padding:1rem}}</style>
</head><body>
<p><a href="/">Inbox</a></p>
{body}
</body></html>"""


def decode(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (UnicodeDecodeError, LookupError):
        return value


def connect():
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    imap.login(IMAP_USER, IMAP_PASSWORD)
    imap.select(MAILBOX, readonly=True)
    return imap


def fetch_headers():
    with connect() as imap:
        status, data = imap.search(None, "ALL")
        if status != "OK":
            return []
        ids = data[0].split()[-MAX_MESSAGES:]
        messages = []
        for msg_id in reversed(ids):
            status, parts = imap.fetch(msg_id, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if status != "OK" or not parts or parts[0] is None:
                continue
            flags = parts[0][0].decode(errors="replace")
            header = email.message_from_bytes(parts[0][1])
            messages.append({
                "id": msg_id.decode(),
                "from": decode(header.get("From")),
                "subject": decode(header.get("Subject")) or "(no subject)",
                "date": header.get("Date", ""),
                "unread": "\\Seen" not in flags,
            })
        return messages


def fetch_message(msg_id):
    with connect() as imap:
        status, parts = imap.fetch(msg_id.encode(), "(BODY.PEEK[])")
        if status != "OK" or not parts or parts[0] is None:
            return None
        return email.message_from_bytes(parts[0][1])


def plain_body(message):
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_type() == "text/plain" and not part.get_filename():
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return "(no plain-text body)"


def format_date(raw):
    try:
        return parsedate_to_datetime(raw).strftime("%d %b %H:%M")
    except (TypeError, ValueError):
        return ""


def render_inbox_rows(messages):
    rows = []
    for msg in messages:
        name, address = parseaddr(msg["from"])
        sender = escape(name or address or "unknown")
        css = ' class="unread"' if msg["unread"] else ""
        rows.append(
            f"<tr{css}><td>{sender}</td>"
            f'<td><a href="/messages/{escape(msg["id"])}">{msg["subject"]}</a></td>'
            f"<td>{escape(format_date(msg['date']))}</td></tr>"
        )
    return "".join(rows)


def html_response(title, body, status_code=200):
    return Response(PAGE.format(title=escape(title), body=body), media_type="text/html", status_code=status_code)


@get("/")
async def inbox() -> Response:
    messages = fetch_headers()
    if not messages:
        return html_response("Inbox", "<h1>Inbox</h1><p>No messages.</p>")
    table = f"<table><tr><th>From</th><th>Subject</th><th>Received</th></tr>{render_inbox_rows(messages)}</table>"
    return html_response("Inbox", f"<h1>Inbox</h1>{table}")


@get("/messages/{msg_id:str}")
async def show_message(msg_id: str) -> Response:
    if not msg_id.isdigit():
        raise NotFoundException()
    message = fetch_message(msg_id)
    if message is None:
        raise NotFoundException()
    subject = decode(message.get("Subject")) or "(no subject)"
    body = (
        f"<h1>{escape(subject)}</h1>"
        f"<p>From: {escape(decode(message.get('From')))}</p>"
        f"<pre>{escape(plain_body(message))}</pre>"
    )
    return html_response(subject, body)


@get("/health")
async def health() -> dict:
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


app = Litestar(route_handlers=[inbox, show_message, health])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))