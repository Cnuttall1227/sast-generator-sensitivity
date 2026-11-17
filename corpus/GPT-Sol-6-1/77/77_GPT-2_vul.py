import argparse
import json
import subprocess
from datetime import datetime, timezone

import click


WORKSHOPS = {
    "woodworking": {
        "title": "Introduction to Woodworking",
        "room": "Workshop A",
        "capacity": 12,
    },
    "screenprinting": {
        "title": "Screenprinting Basics",
        "room": "Art Studio",
        "capacity": 10,
    },
    "bookbinding": {
        "title": "Handmade Bookbinding",
        "room": "Classroom B",
        "capacity": 16,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def print_json(payload):
    click.echo(json.dumps(payload, indent=2))


def workshop_details(workshop_id):
    workshop = WORKSHOPS.get(workshop_id)

    if workshop is None:
        raise click.ClickException("Unknown workshop.")

    return {"id": workshop_id, **workshop}


def format_announcement(workshop_id, audience):
    workshop = workshop_details(workshop_id)
    return (
        f"{workshop['title']} meets in {workshop['room']}. "
        f"Audience: {audience}."
    )


def inspect_printer(queue_name):
    if not isinstance(queue_name, str) or not queue_name.strip():
        return {"ok": False, "error": "Printer queue is required."}

    if len(queue_name) > 150:
        return {"ok": False, "error": "Printer queue is too long."}

    # CWE-77: a CLI option is inserted into a shell command unchecked.
    command = f"lpstat -p {queue_name}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Printer inspection timed out."}
    except OSError:
        return {"ok": False, "error": "Printer inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "queue": queue_name,
        "output": result.stdout[:4000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


@click.group()
def cli():
    """Manage announcements for a community workshop center."""


@cli.command("catalog")
def catalog_command():
    """List scheduled workshops."""
    print_json(
        {
            "workshops": [
                {"id": workshop_id, **details}
                for workshop_id, details in WORKSHOPS.items()
            ]
        }
    )


@cli.command("details")
@click.argument("workshop_id")
def details_command(workshop_id):
    """Display details for one workshop."""
    print_json(workshop_details(workshop_id))


@cli.command("announcement")
@click.argument("workshop_id")
@click.option("--audience", default="all members", show_default=True)
def announcement_command(workshop_id, audience):
    """Preview a workshop announcement."""
    print_json(
        {
            "announcement": format_announcement(workshop_id, audience),
            "created_at": current_time(),
        }
    )


@cli.command("printer-status")
@click.option("--queue", "queue_name", required=True)
def printer_status_command(queue_name):
    """Inspect the printer used for workshop announcement handouts."""
    print_json(inspect_printer(queue_name))


@cli.command("health")
def health_command():
    """Display application status."""
    print_json(
        {
            "status": "ok",
            "workshop_count": len(WORKSHOPS),
            "timestamp": current_time(),
        }
    )


if __name__ == "__main__":
    cli()
