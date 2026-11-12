import os
import json
import time
import asyncio
import logging
from datetime import datetime, timezone

from quart import Quart, jsonify, websocket

BOARD_DIR = os.environ.get("BOARD_DIR", "/srv/whiteboards")
MAX_BOARD_BYTES = 2 * 1024 * 1024
MAX_SHAPES = 5000
SAVE_INTERVAL = 2.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("whiteboard")

app = Quart(__name__)
connections = {}
last_saved = {}


def load_board(board):
    path = os.path.join(BOARD_DIR, f"{board}.json") if board.isidentifier() else None
    if path is None or not os.path.isfile(path):
        return {"shapes": [], "updated": None}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_board(board, shapes):
    path = os.path.join(BOARD_DIR, board + ".json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    document = {
        "shapes": shapes,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(document, handle)
    os.replace(temp_path, path)
    last_saved[board] = time.monotonic()
    return document["updated"]


def valid_shapes(shapes):
    if not isinstance(shapes, list) or len(shapes) > MAX_SHAPES:
        return False
    for shape in shapes:
        if not isinstance(shape, dict) or shape.get("type") not in {"line", "rect", "ellipse", "text"}:
            return False
    return len(json.dumps(shapes)) <= MAX_BOARD_BYTES


async def broadcast(board, message, sender):
    payload = json.dumps(message)
    for queue in list(connections.get(board, set())):
        if queue is not sender:
            await queue.put(payload)


@app.get("/health")
async def health():
    return jsonify(status="ok", boards=len(connections))


@app.get("/boards/<board>")
async def get_board(board):
    if not board.isidentifier():
        return jsonify(error="invalid board name"), 400
    return jsonify(load_board(board))


@app.websocket("/ws")
async def board_socket():
    queue = asyncio.Queue()
    joined = None

    async def sender():
        while True:
            await websocket.send(await queue.get())

    send_task = asyncio.create_task(sender())
    try:
        while True:
            try:
                message = json.loads(await websocket.receive())
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"error": "invalid JSON"}))
                continue
            action = message.get("action")
            if action == "join":
                joined = str(message.get("board", "default"))
                connections.setdefault(joined, set()).add(queue)
                await websocket.send(json.dumps({"action": "state", **load_board(joined)}))
            elif action == "draw" and joined:
                await broadcast(joined, {"action": "draw", "shape": message.get("shape")}, queue)
            elif action == "save" and joined:
                board = str(message.get("board", joined))
                shapes = message.get("shapes")
                if not valid_shapes(shapes):
                    await websocket.send(json.dumps({"error": "invalid shapes"}))
                    continue
                if time.monotonic() - last_saved.get(board, 0) < SAVE_INTERVAL:
                    await websocket.send(json.dumps({"error": "saving too often"}))
                    continue
                updated = save_board(board, shapes)
                await websocket.send(json.dumps({"action": "saved", "updated": updated}))
                await broadcast(joined, {"action": "saved", "updated": updated}, queue)
            else:
                await websocket.send(json.dumps({"error": "unknown or out-of-order action"}))
    except asyncio.CancelledError:
        pass
    finally:
        send_task.cancel()
        if joined and joined in connections:
            connections[joined].discard(queue)
            if not connections[joined]:
                del connections[joined]


if __name__ == "__main__":
    os.makedirs(BOARD_DIR, exist_ok=True)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))