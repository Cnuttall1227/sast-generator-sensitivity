import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


PRINT_JOBS = {
    "flyer": {
        "name": "Community Flyer",
        "ink_ml_per_copy": 0.4,
        "paper_sheets_per_copy": 1,
    },
    "booklet": {
        "name": "Event Booklet",
        "ink_ml_per_copy": 1.8,
        "paper_sheets_per_copy": 6,
    },
    "poster": {
        "name": "Noticeboard Poster",
        "ink_ml_per_copy": 1.2,
        "paper_sheets_per_copy": 2,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def print_catalog():
    return {
        "jobs": [
            {"id": job_id, **details}
            for job_id, details in PRINT_JOBS.items()
        ]
    }


def load_print_order(database_path, order_id):
    database_uri = database_path.resolve().as_uri() + "?mode=ro"

    with sqlite3.connect(database_uri, uri=True) as connection:
        connection.execute("PRAGMA query_only = ON")
        row = connection.execute(
            "SELECT job_id, copies, operator, ink_formula "
            "FROM print_orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()

    if row is None:
        raise ValueError("Print order not found.")

    job_id, copies, operator, formula = row

    if not isinstance(job_id, str) or job_id not in PRINT_JOBS:
        raise ValueError("Unknown print job.")

    if type(copies) is not int or not 1 <= copies <= 5000:
        raise ValueError("Copies must be between 1 and 5000.")

    if not isinstance(operator, str) or not 1 <= len(operator.strip()) <= 100:
        raise ValueError("Invalid operator.")

    if not isinstance(formula, str) or not 1 <= len(formula) <= 500:
        raise ValueError("Invalid ink formula.")

    return {
        "job_id": job_id,
        "copies": copies,
        "operator": operator,
        "ink_formula": formula,
    }


def estimate_ink_usage(order):
    job = PRINT_JOBS[order["job_id"]]

    try:
        # CWE-94: a formula stored in an imported SQLite row becomes Python code.
        ink_ml = eval(
            order["ink_formula"],
            {"__builtins__": __builtins__},
            {
                "copies": order["copies"],
                "ink_per_copy": job["ink_ml_per_copy"],
                "sheets_per_copy": job["paper_sheets_per_copy"],
            },
        )
    except Exception:
        return {"ok": False, "error": "Ink formula failed."}

    if type(ink_ml) not in (int, float) or not 0 <= ink_ml <= 100000:
        return {"ok": False, "error": "Ink usage is outside the allowed range."}

    return {
        "ok": True,
        "estimate": {
            "job_id": order["job_id"],
            "job": job["name"],
            "copies": order["copies"],
            "operator": order["operator"],
            "ink_ml": round(ink_ml, 2),
            "estimated_at": current_time(),
        },
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Estimate print supplies from exported order databases."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("jobs", help="List supported print jobs.")

    estimate = commands.add_parser(
        "estimate",
        help="Estimate ink usage for an imported database order.",
    )
    estimate.add_argument("database", type=Path)
    estimate.add_argument("order_id", type=int)
    return parser


def main():
    args = build_parser().parse_args()

    if args.command == "jobs":
        print(json.dumps(print_catalog(), indent=2))
        return

    try:
        order = load_print_order(args.database, args.order_id)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)

    result = estimate_ink_usage(order)
    print(json.dumps(result, indent=2))

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
