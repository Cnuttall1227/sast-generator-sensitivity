import os
import csv
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import pyodbc
from celery import Celery

BROKER_URL = os.environ.get("STATEMENTS_BROKER", "redis://localhost:6379/3")
MSSQL_DSN = os.environ.get(
    "STATEMENTS_MSSQL_DSN",
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=billing;"
    "UID=statements;PWD=change-me;Encrypt=yes;TrustServerCertificate=no",
)
OUTPUT_DIR = Path(os.environ.get("STATEMENTS_OUTPUT", "/srv/statements"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("statements")

celery_app = Celery("statements", broker=BROKER_URL, backend=BROKER_URL)
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_time_limit=600)


def connect():
    return pyodbc.connect(MSSQL_DSN, timeout=10)


def account_exists(cursor, account_number):
    cursor.execute("SELECT 1 FROM accounts WHERE account_number = ? AND closed_on IS NULL", account_number)
    return cursor.fetchone() is not None


def fetch_month_activity(cursor, account_number, month):
    try:
        start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise ValueError("month must look like YYYY-MM")
    end = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    query = (
        "SELECT t.posted_on, t.description, t.reference, t.amount, t.running_balance "
        "FROM transactions t "
        "JOIN accounts a ON a.id = t.account_id "
        "WHERE a.account_number = ? "
        "AND t.posted_on >= ? AND t.posted_on < ? "
        "ORDER BY t.posted_on, t.id"
    )
    cursor.execute(query, account_number, start, end)
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def opening_balance(cursor, account_number, month):
    cursor.execute(
        "SELECT TOP 1 t.running_balance - t.amount FROM transactions t "
        "JOIN accounts a ON a.id = t.account_id "
        "WHERE a.account_number = ? AND t.posted_on >= DATEFROMPARTS(?, ?, 1) "
        "ORDER BY t.posted_on, t.id",
        account_number, int(month[:4]), int(month[5:7]),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def write_statement(account_number, month, opening, rows):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_account = "".join(ch for ch in account_number if ch.isalnum())
    path = OUTPUT_DIR / f"{safe_account}-{month.replace('-', '')}.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Account", account_number])
        writer.writerow(["Month", month])
        writer.writerow(["Opening balance", "" if opening is None else f"{opening:.2f}"])
        writer.writerow([])
        writer.writerow(["Date", "Description", "Reference", "Amount", "Balance"])
        for row in rows:
            writer.writerow([
                row["posted_on"].strftime("%Y-%m-%d"),
                row["description"],
                row["reference"],
                f"{row['amount']:.2f}",
                f"{row['running_balance']:.2f}",
            ])
    return path


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def generate_statement(self, account_number, month):
    account_number = str(account_number).strip()
    month = str(month).strip()
    try:
        datetime.strptime(month[:7], "%Y-%m")
    except ValueError:
        return {"ok": False, "error": "month must look like YYYY-MM"}
    try:
        with connect() as conn:
            cursor = conn.cursor()
            if not account_exists(cursor, account_number):
                return {"ok": False, "error": "unknown or closed account"}
            rows = fetch_month_activity(cursor, account_number, month)
            opening = opening_balance(cursor, account_number, month)
    except pyodbc.OperationalError as exc:
        raise self.retry(exc=exc)
    path = write_statement(account_number, month, opening, rows)
    log.info("Statement for %s %s: %d transaction(s)", account_number, month, len(rows))
    return {
        "ok": True,
        "file": path.name,
        "transactions": len(rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@celery_app.task
def generate_all_statements(month):
    with connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT account_number FROM accounts WHERE closed_on IS NULL")
        accounts = [row[0] for row in cursor.fetchall()]
    for account_number in accounts:
        generate_statement.delay(account_number, month)
    return {"queued": len(accounts), "month": month}


if __name__ == "__main__":
    celery_app.worker_main(["worker", "--loglevel=INFO", "--concurrency=4"])