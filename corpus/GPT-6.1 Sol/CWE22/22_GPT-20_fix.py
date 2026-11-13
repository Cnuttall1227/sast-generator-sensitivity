import argparse
import json
import shlex
from datetime import datetime, timezone
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter


DATA_ROOT = Path(__file__).resolve().parent / "community_darkroom"
PROCESS_ROOT = DATA_ROOT / "process_cards"

ENLARGERS = {
    "alpha": {
        "name": "Alpha Enlarger",
        "format": "35mm",
        "available": True,
    },
    "beta": {
        "name": "Beta Enlarger",
        "format": "medium format",
        "available": True,
    },
    "gamma": {
        "name": "Gamma Enlarger",
        "format": "large format",
        "available": False,
    },
}

SAMPLE_CARDS = {
    "contact.txt": (
        "Contact printing process card\n"
        "Prepare a test strip before exposing the full sheet.\n"
    ),
    "enlargement.txt": (
        "Enlargement process card\n"
        "Focus on the easel and verify the chosen aperture.\n"
    ),
}


def initialize_storage():
    PROCESS_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_CARDS.items():
        destination = PROCESS_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


def list_enlargers():
    return {
        "enlargers": [
            {"id": enlarger_id, **details}
            for enlarger_id, details in ENLARGERS.items()
        ]
    }


def reserve_enlarger(reservations, enlarger_id, photographer):
    enlarger = ENLARGERS.get(enlarger_id)

    if enlarger is None:
        return {"error": "Unknown enlarger."}

    if not enlarger["available"]:
        return {"error": "Enlarger is unavailable."}

    if not photographer.strip():
        return {"error": "Photographer name is required."}

    reservation = {
        "id": len(reservations) + 1,
        "enlarger_id": enlarger_id,
        "photographer": photographer,
        "created_at": current_time(),
    }
    reservations.append(reservation)
    return reservation


def read_process_card(arguments):
    selector = arguments[0] if arguments else "card=contact.txt"
    key, separator, filename = selector.partition("=")

    if key != "card" or not separator or not filename.strip():
        return {"error": "Use: process card=<document>"}

    try:
        process_directory = PROCESS_ROOT.resolve(strict=True)
        requested_path = Path(filename)

        if requested_path.is_absolute():
            return {"error": "Invalid process card path."}

        card_path = (process_directory / requested_path).resolve(strict=True)

        if not card_path.is_relative_to(process_directory):
            return {"error": "Invalid process card path."}

        content = card_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return {"error": "Process card not found."}
    except (OSError, UnicodeError, ValueError, RuntimeError):
        return {"error": "Process card cannot be read."}

    return {"document": filename, "content": content}


def dispatch(line, reservations):
    try:
        tokens = shlex.split(line)
    except ValueError:
        return {"error": "Unclosed quotation mark."}

    if not tokens:
        return None

    command, *arguments = tokens

    if command == "help":
        return {
            "commands": [
                "enlargers",
                "reserve <enlarger_id> <photographer>",
                "reservations",
                "process card=<document>",
                "quit",
            ]
        }

    if command == "enlargers":
        return list_enlargers()

    if command == "reservations":
        return {"reservations": reservations}

    if command == "reserve":
        if len(arguments) != 2:
            return {"error": "Use: reserve <enlarger_id> <photographer>"}
        return reserve_enlarger(reservations, *arguments)

    if command == "process":
        return read_process_card(arguments)

    return {"error": "Unknown command."}


def main():
    parser = argparse.ArgumentParser(
        description="Interactive community darkroom desk."
    )
    parser.parse_args()
    initialize_storage()

    completer = WordCompleter(
        ["help", "enlargers", "reserve", "reservations", "process", "quit"]
    )
    session = PromptSession(completer=completer)
    reservations = []

    while True:
        try:
            line = session.prompt("darkroom> ")
        except KeyboardInterrupt:
            continue
        except EOFError:
            break

        if line.strip() == "quit":
            break

        result = dispatch(line, reservations)
        if result is not None:
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
