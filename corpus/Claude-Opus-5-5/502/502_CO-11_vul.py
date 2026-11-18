import os
import sys
import shelve
import json
from datetime import datetime, timedelta
from pathlib import Path

import click

DEFAULT_DB = Path.home() / ".timetrack" / "entries"


def open_db(path, flag="c"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return shelve.open(str(path), flag=flag)


def parse_duration(text):
    text = text.strip().lower()
    hours, minutes = 0, 0
    if "h" in text:
        hours_part, _, text = text.partition("h")
        hours = int(hours_part or 0)
    if text.endswith("m"):
        minutes = int(text[:-1] or 0)
    elif text:
        minutes = int(text)
    if hours < 0 or minutes < 0 or (hours == 0 and minutes == 0):
        raise click.BadParameter("use a duration like 1h30m, 45m or 2h")
    return timedelta(hours=hours, minutes=minutes)


def entry_key(when, project):
    return f"{when:%Y%m%d%H%M%S%f}:{project}"


def import_entries(source_path, db):
    with open(source_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise click.ClickException("the export must be a JSON list of entries")
    imported = skipped = 0
    for item in data[:50000]:
        try:
            project = str(item["project"]).strip()[:80]
            start = datetime.fromisoformat(str(item["start"]))
            seconds = item["duration_seconds"]
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 < seconds <= 24 * 3600:
                raise ValueError("bad duration")
            note = str(item.get("note", ""))[:200]
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if not project:
            skipped += 1
            continue
        key = entry_key(start, project)
        if key in db:
            skipped += 1
            continue
        db[key] = {"project": project, "start": start, "duration": timedelta(seconds=seconds), "note": note}
        imported += 1
    return imported, skipped


@click.group()
@click.option("--db", default=str(DEFAULT_DB), show_default=True, help="Where your entries are stored")
@click.pass_context
def cli(ctx, db):
    """Track time spent on projects."""
    ctx.obj = db


@cli.command()
@click.argument("project")
@click.argument("duration")
@click.option("--note", default="", help="What you worked on")
@click.option("--date", "day", default=None, help="Date of the work (YYYY-MM-DD), default today")
@click.pass_obj
def log(db_path, project, duration, note, day):
    """Log DURATION (e.g. 1h30m) against PROJECT."""
    spent = parse_duration(duration)
    start = datetime.strptime(day, "%Y-%m-%d") if day else datetime.now() - spent
    with open_db(db_path) as db:
        db[entry_key(start, project)] = {"project": project, "start": start, "duration": spent, "note": note[:200]}
    click.echo(f"Logged {spent} on {project}.")


@cli.command()
@click.option("--days", default=7, show_default=True, help="How many days back to include")
@click.pass_obj
def report(db_path, days):
    """Show time per project for the last N days."""
    since = datetime.now() - timedelta(days=days)
    totals = {}
    with open_db(db_path, flag="r" if Path(f"{db_path}.db").exists() or Path(db_path).exists() else "c") as db:
        for entry in db.values():
            if entry["start"] >= since:
                totals[entry["project"]] = totals.get(entry["project"], timedelta()) + entry["duration"]
    if not totals:
        click.echo("Nothing logged in that period.")
        return
    width = max(len(p) for p in totals)
    for project, spent in sorted(totals.items(), key=lambda item: item[1], reverse=True):
        hours = spent.total_seconds() / 3600
        click.echo(f"{project.ljust(width)}  {hours:6.2f} h  {'█' * int(hours * 2)}")


@cli.command("import")
@click.argument("source", type=click.Path(dir_okay=False))
@click.pass_obj
def import_command(db_path, source):
    """Merge entries from a teammate's exported database."""
    base = source[:-3] if source.endswith((".db", ".dat", ".dir", ".bak")) else source
    if not any(Path(base + suffix).exists() for suffix in ("", ".db", ".dat")):
        raise click.ClickException(f"no database found at {source}")
    with open_db(db_path) as db:
        imported, skipped = import_entries(base, db)
    click.echo(f"Imported {imported} entr{'y' if imported == 1 else 'ies'}, skipped {skipped}.")


if __name__ == "__main__":
    try:
        cli()
    except KeyboardInterrupt:
        sys.exit(130)