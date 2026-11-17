import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml


INSTRUMENTS = {
    "violin": {
        "name": "Student Violin",
        "category": "strings",
        "available": 6,
    },
    "clarinet": {
        "name": "Student Clarinet",
        "category": "woodwinds",
        "available": 4,
    },
    "trumpet": {
        "name": "Student Trumpet",
        "category": "brass",
        "available": 3,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def instrument_catalog():
    return {
        "instruments": [
            {"id": instrument_id, **details}
            for instrument_id, details in INSTRUMENTS.items()
        ]
    }


def import_loan_document(document):
    if not isinstance(document, str) or not document.strip():
        return {"ok": False, "error": "Loan document is required."}

    try:
        if len(document.encode("utf-8")) > 16384:
            return {"ok": False, "error": "Loan document is too large."}

        loan = yaml.safe_load(document)
    except (yaml.YAMLError, UnicodeError, ValueError, RecursionError):
        return {"ok": False, "error": "Loan document could not be decoded."}

    if not isinstance(loan, dict):
        return {"ok": False, "error": "Loan document must contain a mapping."}

    instrument_id = loan.get("instrument_id")
    borrower = loan.get("borrower")
    weeks = loan.get("weeks")

    if not isinstance(instrument_id, str) or instrument_id not in INSTRUMENTS:
        return {"ok": False, "error": "Unknown instrument."}

    if not isinstance(borrower, str) or not borrower.strip():
        return {"ok": False, "error": "Borrower is required."}

    if type(weeks) is not int or not 1 <= weeks <= 12:
        return {"ok": False, "error": "Loan duration must be 1–12 weeks."}

    return {
        "ok": True,
        "loan": {
            "instrument_id": instrument_id,
            "borrower": borrower,
            "weeks": weeks,
            "imported_at": current_time(),
        },
    }


def read_document(document_path):
    with document_path.open("r", encoding="utf-8") as source:
        document = source.read(16385)

    if len(document) > 16384:
        raise ValueError("Loan document is too large.")

    return document


def build_parser():
    parser = argparse.ArgumentParser(
        description="Import instrument loans for a community music school."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="List loan instruments.")

    import_command = commands.add_parser(
        "import-loan",
        help="Import a loan from a YAML document.",
    )
    import_command.add_argument("document", type=Path)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "catalog":
        print(json.dumps(instrument_catalog(), indent=2))
        return

    try:
        document = read_document(args.document)
        result = import_loan_document(document)
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
