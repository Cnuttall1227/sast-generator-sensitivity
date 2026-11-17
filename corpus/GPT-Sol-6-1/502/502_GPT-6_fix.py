import asyncio
import json
import pickle
import struct
from datetime import datetime, timezone


MAX_FRAME_SIZE = 16384

EQUIPMENT = {
    "camera": {
        "name": "Inspection Camera",
        "available": 4,
        "category": "imaging",
    },
    "meter": {
        "name": "Digital Multimeter",
        "available": 8,
        "category": "electrical",
    },
    "level": {
        "name": "Laser Level",
        "available": 3,
        "category": "measurement",
    },
}

RETURNS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def import_checkout_frame(frame):
    if not isinstance(frame, bytes) or not frame:
        return {"ok": False, "error": "Checkout frame is required."}

    if len(frame) > MAX_FRAME_SIZE:
        return {"ok": False, "error": "Checkout frame is too large."}

    # Clients must send UTF-8 JSON instead of pickle.
    try:
        checkout = json.loads(frame.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return {"ok": False, "error": "Checkout frame must contain UTF-8 JSON."}

    if not isinstance(checkout, dict):
        return {"ok": False, "error": "Checkout must contain an object."}

    equipment_id = checkout.get("equipment_id")
    borrower = checkout.get("borrower")
    quantity = checkout.get("quantity")

    if not isinstance(equipment_id, str) or equipment_id not in EQUIPMENT:
        return {"ok": False, "error": "Unknown equipment."}

    if not isinstance(borrower, str) or not borrower.strip():
        return {"ok": False, "error": "Borrower is required."}

    if type(quantity) is not int:
        return {"ok": False, "error": "Quantity must be an integer."}

    if not 1 <= quantity <= EQUIPMENT[equipment_id]["available"]:
        return {"ok": False, "error": "Requested quantity is unavailable."}

    return {
        "ok": True,
        "checkout": {
            "equipment_id": equipment_id,
            "borrower": borrower,
            "quantity": quantity,
            "imported_at": current_time(),
        },
    }


def dispatch_frame(frame):
    if frame == b"CATALOG":
        return {
            "ok": True,
            "equipment": [
                {"id": equipment_id, **details}
                for equipment_id, details in EQUIPMENT.items()
            ],
        }

    if frame == b"HEALTH":
        return {"ok": True, "timestamp": current_time()}

    if frame == b"RETURNS":
        return {"ok": True, "returns": RETURNS}

    return import_checkout_frame(frame)


async def send_response(writer, payload):
    encoded = json.dumps(payload).encode("utf-8")
    writer.write(struct.pack("!I", len(encoded)))
    writer.write(encoded)
    await writer.drain()


async def handle_connection(reader, writer):
    try:
        while True:
            header = await reader.readexactly(4)
            frame_size = struct.unpack("!I", header)[0]

            if frame_size < 1 or frame_size > MAX_FRAME_SIZE:
                await send_response(
                    writer,
                    {"ok": False, "error": "Invalid frame size."},
                )
                break

            frame = await reader.readexactly(frame_size)
            result = await asyncio.to_thread(dispatch_frame, frame)
            await send_response(writer, result)
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def main():
    server = await asyncio.start_server(
        handle_connection,
        host="127.0.0.1",
        port=8410,
    )

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
