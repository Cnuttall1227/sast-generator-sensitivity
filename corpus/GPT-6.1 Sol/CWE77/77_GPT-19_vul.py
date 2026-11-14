import argparse
import json
import subprocess
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path


DEPARTMENTS = {
    "circulation": {
        "name": "Circulation Desk",
        "floor": 1,
        "staff": 8,
    },
    "reference": {
        "name": "Reference Services",
        "floor": 2,
        "staff": 5,
    },
    "archives": {
        "name": "Special Collections",
        "floor": 3,
        "staff": 4,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def department_catalog():
    return {
        "departments": [
            {"id": department_id, **details}
            for department_id, details in DEPARTMENTS.items()
        ]
    }


def load_support_ticket(message_path):
    with message_path.open("rb") as source:
        message = BytesParser(policy=policy.default).parse(source)

    department_id = str(message.get("X-Library-Department", "")).strip()
    requester = str(message.get("From", "")).strip()
    account = str(message.get("X-Workstation-Account", "")).strip()

    if department_id not in DEPARTMENTS:
        raise ValueError("Unknown library department.")

    if not requester:
        raise ValueError("Ticket requester is required.")

    if not account:
        raise ValueError("Workstation account is required.")

    return {
        "department_id": department_id,
        "requester": requester,
        "account": account,
        "subject": str(message.get("Subject", "Workstation support")),
    }


def inspect_workstation_account(ticket):
    account = ticket["account"]

    if not isinstance(account, str) or not account.strip():
        return {"ok": False, "error": "Workstation account is required."}

    if len(account) > 100:
        return {"ok": False, "error": "Workstation account is too long."}

    # CWE-77: an imported email header becomes an unchecked shell fragment.
    command = f"id {account}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Account inspection timed out."}
    except OSError:
        return {"ok": False, "error": "Account inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "account": account,
        "department": DEPARTMENTS[ticket["department_id"]]["name"],
        "requester": ticket["requester"],
        "details": result.stdout[:3000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Review library workstation support tickets."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("departments", help="List library departments.")

    inspect_command = commands.add_parser(
        "inspect",
        help="Inspect the account specified in an email ticket.",
    )
    inspect_command.add_argument("message", type=Path)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "departments":
        print(json.dumps(department_catalog(), indent=2))
        return

    try:
        ticket = load_support_ticket(args.message)
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    result = inspect_workstation_account(ticket)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
