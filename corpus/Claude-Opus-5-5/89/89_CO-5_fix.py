import csv
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

import click

DEFAULT_DB = Path.home() / ".local" / "share" / "library-tracker" / "books.db"
REQUIRED_COLUMNS = {"isbn", "title", "author"}


def connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS books (
               isbn TEXT PRIMARY KEY,
               title TEXT NOT NULL,
               author TEXT NOT NULL,
               shelf TEXT,
               added_on TEXT NOT NULL,
               loaned_to TEXT)"""
    )
    return conn


def clean_isbn(raw):
    digits = "".join(ch for ch in raw if ch.isdigit() or ch in "Xx")
    return digits.upper() if len(digits) in (10, 13) else None


def import_rows(conn, rows):
    added_on = datetime.now().date().isoformat()
    records = [
        (
            row["isbn"],
            row["title"].strip(),
            row["author"].strip(),
            (row.get("shelf") or "").strip(),
            added_on,
        )
        for row in rows
    ]
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO books (isbn, title, author, shelf, added_on) VALUES (?, ?, ?, ?, ?)",
            records,
        )
    return len(records)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = {c.strip().lower() for c in reader.fieldnames or []}
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise click.ClickException(f"CSV is missing columns: {', '.join(sorted(missing))}")
        valid, skipped = [], 0
        for raw in reader:
            row = {k.strip().lower(): (v or "") for k, v in raw.items() if k}
            isbn = clean_isbn(row.get("isbn", ""))
            if not isbn or not row.get("title", "").strip() or not row.get("author", "").strip():
                skipped += 1
                continue
            row["isbn"] = isbn
            valid.append(row)
        return valid, skipped


@click.group()
@click.option("--db", default=str(DEFAULT_DB), show_default=True, help="Path to the library database")
@click.pass_context
def cli(ctx, db):
    """Track a home library: import, list, lend and return books."""
    ctx.obj = connect(db)


@cli.command("import")
@click.argument("csv_file", type=click.Path(exists=True, dir_okay=False))
@click.pass_obj
def import_command(conn, csv_file):
    """Import books from a CSV export (isbn, title, author[, shelf])."""
    rows, skipped = read_csv(csv_file)
    if not rows:
        raise click.ClickException("No valid rows found")
    before = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    import_rows(conn, rows)
    after = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    click.echo(f"Imported {after - before} new book(s); {skipped} row(s) skipped, "
               f"{len(rows) - (after - before)} already present.")


@cli.command("list")
@click.option("--shelf", help="Only show one shelf")
@click.option("--loaned", is_flag=True, help="Only show books currently lent out")
@click.pass_obj
def list_command(conn, shelf, loaned):
    """List books in the library."""
    sql = "SELECT isbn, title, author, shelf, loaned_to FROM books WHERE 1=1"
    params = []
    if shelf:
        sql += " AND shelf = ?"
        params.append(shelf)
    if loaned:
        sql += " AND loaned_to IS NOT NULL"
    for book in conn.execute(sql + " ORDER BY author, title", params):
        loan = f"  → {book['loaned_to']}" if book["loaned_to"] else ""
        click.echo(f"{book['isbn']}  {book['title']} — {book['author']} [{book['shelf'] or '-'}]{loan}")


@cli.command()
@click.argument("isbn")
@click.argument("borrower")
@click.pass_obj
def lend(conn, isbn, borrower):
    """Record that a book was lent to someone."""
    with conn:
        updated = conn.execute(
            "UPDATE books SET loaned_to = ? WHERE isbn = ? AND loaned_to IS NULL",
            (borrower.strip()[:80], clean_isbn(isbn)),
        ).rowcount
    click.echo("Recorded." if updated else "Book not found or already lent out.")


@cli.command("return")
@click.argument("isbn")
@click.pass_obj
def return_command(conn, isbn):
    """Mark a lent book as returned."""
    with conn:
        updated = conn.execute("UPDATE books SET loaned_to = NULL WHERE isbn = ?", (clean_isbn(isbn),)).rowcount
    click.echo("Returned." if updated else "That book wasn't lent out.")


if __name__ == "__main__":
    try:
        cli()
    except sqlite3.Error as exc:
        click.echo(f"Database error: {exc}", err=True)
        sys.exit(1)