import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path


DATA_ROOT = Path(__file__).resolve().parent / "aquarium_data"
CARE_ROOT = DATA_ROOT / "care_sheets"
MAX_MESSAGE_SIZE = 8192

TANKS = {
    "reef": {
        "name": "Coral Reef",
        "water_type": "saltwater",
        "temperature_c": 25,
    },
    "river": {
        "name": "River Habitat",
        "water_type": "freshwater",
        "temperature_c": 23,
    },
    "kelp": {
        "name": "Kelp Forest",
        "water_type": "saltwater",
        "temperature_c": 15,
    },
}

SAMPLE_CARE_SHEETS = {
    "reef.txt": (
        "Coral Reef care sheet\n"
        "Inspect circulation pumps each morning.\n"
        "Record salinity before feeding.\n"
    ),
    "river.txt": (
        "River Habitat care sheet\n"
        "Inspect filtration and record water clarity.\n"
        "Feed according to the freshwater schedule.\n"
    ),
    "kelp.txt": (
        "Kelp Forest care sheet\n"
        "Verify chiller temperature and inspect lighting.\n"
        "Check kelp attachment points.\n"
    ),
}

FEEDING_RECORDS = []


def initialize_storage():
    CARE_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_CARE_SHEETS.items():
        destination = CARE_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


def list_tanks(message):
    return {
        "ok": True,
        "tanks": [
            {"id": tank_id, **details}
            for tank_id, details in TANKS.items()
        ],
    }


def record_feeding(message):
    tank_id = message.get("tank_id")
    food = message.get("food")

    if not isinstance(tank_id, str) or tank_id not in TANKS:
        return {"ok": False, "error": "Unknown tank."}

    if not isinstance(food, str) or not food.strip():
        return {"ok": False, "error": "Food must be a nonempty string."}

    record = {
        "id": len(FEEDING_RECORDS) + 1,
        "tank_id": tank_id,
        "food": food,
        "timestamp": current_time(),
    }
    FEEDING_RECORDS.append(record)
    return {"ok": True, "record": record}


def read_care_sheet(message):
    document = message.get("document", {})

    if not isinstance(document, dict):
        return {"ok": False, "error": "Document must be an object."}

    filename = document.get("location", "reef.txt")

    if not isinstance(filename, str) or not filename:
        return {"ok": False, "error": "Location must be a nonempty string."}

    # CWE-22: a nested field in a TCP JSON message controls the file path.
    care_path = CARE_ROOT / filename

    try:
        content = care_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return {"ok": False, "error": "Care sheet not found."}
    except (OSError, UnicodeError, ValueError):
        return {"ok": False, "error": "Care sheet cannot be read."}

    return {"ok": True, "location": filename, "content": content}


def dispatch(message):
    if not isinstance(message, dict):
        return {"ok": False, "error": "Message must be an object."}

    action = message.get("action")

    if not isinstance(action, str):
        return {"ok": False, "error": "Action must be a string."}

    if action == "health":
        return {"ok": True, "timestamp": current_time()}

    if action == "list_tanks":
        return list_tanks(message)

    if action == "record_feeding":
        return record_feeding(message)

    if action == "read_care_sheet":
        return read_care_sheet(message)

    return {"ok": False, "error": "Unknown action."}


async def handle_client(reader, writer):
    try:
        while True:
            try:
                line = await reader.readline()
            except ValueError:
                break

            if not line:
                break

            if len(line) > MAX_MESSAGE_SIZE:
                response = {"ok": False, "error": "Message too large."}
            else:
                try:
                    message = json.loads(line)
                    response = dispatch(message)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    response = {"ok": False, "error": "Invalid JSON."}

            writer.write(
                (json.dumps(response) + "\n").encode("utf-8")
            )
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def main():
    initialize_storage()
    server = await asyncio.start_server(
        handle_client,
        host="127.0.0.1",
        port=8100,
        limit=MAX_MESSAGE_SIZE,
    )

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
