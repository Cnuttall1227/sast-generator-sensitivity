import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import typer


app = typer.Typer(help="Prepare accessibility checks for walking tours.")

TOURS = {
    "historic": {
        "title": "Historic Main Street",
        "distance_km": 2.1,
        "meeting_point": "Town Hall",
    },
    "sculpture": {
        "title": "Outdoor Sculpture Walk",
        "distance_km": 1.4,
        "meeting_point": "Arts Center",
    },
    "river": {
        "title": "River Heritage Trail",
        "distance_km": 3.2,
        "meeting_point": "Visitor Pavilion",
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def print_result(payload):
    typer.echo(json.dumps(payload, indent=2))


def load_stops(csv_path):
    stops = []

    with csv_path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        required = {"tour_id", "stop_name", "speech_text"}

        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(
                "CSV requires tour_id, stop_name, and speech_text columns."
            )

        for row_number, row in enumerate(reader, start=2):
            tour_id = row.get("tour_id")
            stop_name = row.get("stop_name")
            speech_text = row.get("speech_text")

            if tour_id not in TOURS:
                raise ValueError(f"Unknown tour on row {row_number}.")

            if not isinstance(stop_name, str) or not stop_name.strip():
                raise ValueError(f"Missing stop name on row {row_number}.")

            if not isinstance(speech_text, str) or not speech_text.strip():
                raise ValueError(f"Missing speech text on row {row_number}.")

            stops.append(
                {
                    "tour_id": tour_id,
                    "stop_name": stop_name,
                    "speech_text": speech_text,
                }
            )

    return stops


def check_pronunciation(stop):
    speech_text = stop["speech_text"]

    if not isinstance(speech_text, str) or not speech_text.strip():
        return {"ok": False, "error": "Speech text is required."}

    if len(speech_text) > 500:
        return {"ok": False, "error": "Speech text is too long."}

    try:
        result = subprocess.run(
            ["espeak", "--quiet", "--stdin"],
            input=speech_text,
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Pronunciation check timed out."}
    except (OSError, ValueError):
        return {"ok": False, "error": "Pronunciation check could not start."}

    return {
        "ok": result.returncode == 0,
        "tour_id": stop["tour_id"],
        "stop_name": stop["stop_name"],
        "speech_text": speech_text,
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


@app.command("catalog")
def catalog():
    print_result(
        {
            "tours": [
                {"id": tour_id, **details}
                for tour_id, details in TOURS.items()
            ]
        }
    )


@app.command("check")
def check(csv_path: Path):
    try:
        stops = load_stops(csv_path)
    except (OSError, UnicodeError, ValueError, csv.Error) as error:
        print_result({"ok": False, "error": str(error)})
        raise typer.Exit(code=1)

    results = [check_pronunciation(stop) for stop in stops]
    print_result({"results": results})

    if any(not result["ok"] for result in results):
        raise typer.Exit(code=1)


@app.command("health")
def health():
    print_result(
        {
            "status": "ok",
            "tour_count": len(TOURS),
            "timestamp": current_time(),
        }
    )


if __name__ == "__main__":
    app()
