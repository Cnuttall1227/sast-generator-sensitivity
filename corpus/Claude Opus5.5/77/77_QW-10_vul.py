import csv
import re
import sys
import json
import secrets
import subprocess
from pathlib import Path

import click

USERNAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
ALLOWED_GROUPS = {"developers", "analysts", "support", "ops"}
DEFAULT_SHELL = "/bin/bash"
REQUIRED_COLUMNS = {"username", "full_name", "group"}


def user_exists(username):
    result = subprocess.run(["id", "-u", username], capture_output=True, text=True)
    return result.returncode == 0


def ensure_group(group):
    result = subprocess.run(["getent", "group", group], capture_output=True, text=True)
    if result.returncode != 0:
        subprocess.run(["groupadd", group], check=True)


def create_account(username, full_name, group, shell):
    command = (
        f"useradd --create-home --shell {shell} --gid {group} "
        f"--comment \"{full_name}\" {username}"
    )
    status, output = subprocess.getstatusoutput(command)
    if status != 0:
        raise RuntimeError(output.strip() or f"useradd exited with {status}")
    return output


def set_temporary_password(username):
    password = secrets.token_urlsafe(12)
    subprocess.run(["chpasswd"], input=f"{username}:{password}\n", text=True, check=True)
    subprocess.run(["chage", "-d", "0", username], check=True)
    return password


def read_roster(path):
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise click.ClickException(f"Roster is missing columns: {', '.join(sorted(missing))}")
        rows = []
        for line_number, row in enumerate(reader, start=2):
            username = row["username"].strip().lower()
            group = row["group"].strip().lower()
            if not USERNAME_PATTERN.fullmatch(username):
                raise click.ClickException(f"Line {line_number}: invalid username {username!r}")
            if group not in ALLOWED_GROUPS:
                raise click.ClickException(f"Line {line_number}: group {group!r} is not allowed")
            rows.append({"username": username, "full_name": row["full_name"].strip(), "group": group})
        return rows


@click.group()
def cli():
    """Provision Linux accounts from an HR roster CSV."""


@cli.command()
@click.argument("roster", type=click.Path(exists=True, dir_okay=False))
def check(roster):
    """Validate a roster without changing anything."""
    rows = read_roster(roster)
    new = [r for r in rows if not user_exists(r["username"])]
    click.echo(f"{len(rows)} row(s) valid, {len(new)} account(s) would be created")


@cli.command()
@click.argument("roster", type=click.Path(exists=True, dir_okay=False))
@click.option("--shell", default=DEFAULT_SHELL, type=click.Choice(["/bin/bash", "/bin/zsh", "/bin/sh"]))
@click.option("--report", type=click.Path(dir_okay=False), help="Write created credentials to this JSON file")
@click.option("--dry-run", is_flag=True, help="Show what would happen")
def provision(roster, shell, report, dry_run):
    """Create accounts listed in the roster."""
    rows = read_roster(roster)
    created = []
    for row in rows:
        if user_exists(row["username"]):
            click.echo(f"skip    {row['username']} (exists)")
            continue
        if dry_run:
            click.echo(f"would   {row['username']} -> {row['group']}")
            continue
        ensure_group(row["group"])
        try:
            create_account(row["username"], row["full_name"], row["group"], shell)
        except RuntimeError as exc:
            click.echo(f"failed  {row['username']}: {exc}", err=True)
            continue
        password = set_temporary_password(row["username"])
        created.append({"username": row["username"], "temporary_password": password})
        click.echo(f"created {row['username']}")
    if report and created:
        report_path = Path(report)
        report_path.write_text(json.dumps(created, indent=2), encoding="utf-8")
        report_path.chmod(0o600)
        click.echo(f"Credentials written to {report_path}")
    click.echo(f"Done: {len(created)} account(s) created")


if __name__ == "__main__":
    if sys.platform != "linux":
        raise SystemExit("This tool only runs on Linux")
    cli()