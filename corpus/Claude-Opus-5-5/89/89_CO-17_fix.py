import os
import logging

import oracledb
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
ORACLE_DSN = os.environ.get("TICKETS_ORACLE_DSN", "localhost:1521/FREEPDB1")
ORACLE_USER = os.environ.get("TICKETS_ORACLE_USER", "ticket_reader")
ORACLE_PASSWORD = os.environ.get("TICKETS_ORACLE_PASSWORD", "")
ALLOWED_CHANNELS = set(filter(None, os.environ.get("TICKETS_CHANNELS", "").split(",")))
MAX_RESULTS = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ticket-bot")

pool = oracledb.create_pool(user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN, min=1, max=4)
app = App(token=SLACK_BOT_TOKEN)

HELP = (
    "*Usage*\n"
    "• `/tickets 4821` – show one ticket\n"
    "• `/tickets search printer jam` – search open tickets by keyword\n"
    "• `/tickets mine` – tickets assigned to you"
)
STATUS_EMOJI = {"OPEN": ":large_yellow_circle:", "IN_PROGRESS": ":large_blue_circle:", "CLOSED": ":white_check_mark:"}


def rows_as_dicts(cursor):
    columns = [c[0].lower() for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_ticket(ticket_id):
    with pool.acquire() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, status, priority, assignee_slack_id, created_at "
            "FROM tickets WHERE id = :id",
            id=ticket_id,
        )
        rows = rows_as_dicts(cur)
    return rows[0] if rows else None


def search_open_tickets(keywords):
    conditions = []
    binds = {}
    for index, word in enumerate(keywords[:5]):
        escaped = str(word)[:30].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        name = f"kw{index}"
        conditions.append(f"UPPER(title) LIKE UPPER(:{name}) ESCAPE '\\'")
        binds[name] = f"%{escaped}%"
    if not conditions:
        return []
    binds["max_rows"] = MAX_RESULTS
    sql = (
        "SELECT id, title, status, priority FROM tickets "
        f"WHERE status <> 'CLOSED' AND {' AND '.join(conditions)} "
        "ORDER BY priority, created_at DESC FETCH FIRST :max_rows ROWS ONLY"
    )
    with pool.acquire() as conn, conn.cursor() as cur:
        cur.execute(sql, binds)
        return rows_as_dicts(cur)


def tickets_for_assignee(slack_user_id):
    with pool.acquire() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, status, priority FROM tickets "
            "WHERE assignee_slack_id = :uid AND status <> 'CLOSED' "
            "ORDER BY priority, created_at FETCH FIRST :n ROWS ONLY",
            uid=slack_user_id, n=MAX_RESULTS,
        )
        return rows_as_dicts(cur)


def format_ticket_line(ticket):
    emoji = STATUS_EMOJI.get(ticket["status"], ":grey_question:")
    title = ticket["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"{emoji} *#{ticket['id']}* {title} (P{ticket['priority']})"


@app.command("/tickets")
def handle_tickets(ack, respond, command):
    ack()
    if ALLOWED_CHANNELS and command.get("channel_id") not in ALLOWED_CHANNELS:
        respond("Ticket lookups aren't enabled in this channel.")
        return
    text = (command.get("text") or "").strip()
    parts = text.split()
    try:
        if not parts:
            respond(HELP)
        elif parts[0].isdigit():
            ticket = get_ticket(int(parts[0]))
            respond(format_ticket_line(ticket) if ticket else f"No ticket #{parts[0]}.")
        elif parts[0].lower() == "search" and len(parts) > 1:
            keywords = [w[:30] for w in parts[1:6]]
            results = search_open_tickets(keywords)
            if not results:
                respond("No open tickets match those words.")
            else:
                respond("\n".join(format_ticket_line(t) for t in results))
        elif parts[0].lower() == "mine":
            results = tickets_for_assignee(command.get("user_id", ""))
            respond("\n".join(format_ticket_line(t) for t in results) or "Nothing assigned to you.")
        else:
            respond(HELP)
    except oracledb.DatabaseError as exc:
        log.error("Ticket query failed: %s", exc)
        respond("The ticket database isn't responding right now.")


@app.event("app_mention")
def mention(say):
    say(HELP)


if __name__ == "__main__":
    log.info("Ticket bot starting")
    SocketModeHandler(app, SLACK_APP_TOKEN).start()