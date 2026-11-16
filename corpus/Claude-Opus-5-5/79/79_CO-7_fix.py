import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from html import escape

from quart import Quart, websocket

MAX_MESSAGE_LENGTH = 500
MAX_NAME_LENGTH = 32
HISTORY_SIZE = 50

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("support-chat")

app = Quart(__name__)
clients = set()
history = []

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Community help desk</title>
<style>
body{font-family:sans-serif;max-width:40rem;margin:2rem auto}
#log{border:1px solid #ccc;height:24rem;overflow-y:auto;padding:.5rem}
.msg{margin:.25rem 0}.who{font-weight:bold}.when{color:#888;font-size:.8rem}
</style></head><body>
<h1>Community help desk</h1>
<div id="log"></div>
<form id="send">
  <input id="name" placeholder="Your name" maxlength="32" required>
  <input id="text" placeholder="Ask a question" maxlength="500" required size="40">
  <button>Send</button>
</form>
<script>
const log = document.getElementById("log");
const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  for (const fragment of data.fragments) {
    log.insertAdjacentHTML("beforeend", fragment);
  }
  log.scrollTop = log.scrollHeight;
};
document.getElementById("send").onsubmit = (event) => {
  event.preventDefault();
  const text = document.getElementById("text");
  ws.send(JSON.stringify({name: document.getElementById("name").value, text: text.value}));
  text.value = "";
};
</script>
</body></html>"""


def render_message_fragment(name, text, sent_at):
    when = escape(sent_at.strftime("%H:%M"))
    safe_name = escape(name)
    if text.startswith("/me "):
        action = escape(text[4:]).replace("\n", "<br>")
        return f'<div class="msg"><em>{safe_name} {action}</em> <span class="when">{when}</span></div>'
    body = escape(text).replace("\n", "<br>")
    return (
        f'<div class="msg"><span class="who">{safe_name}</span> '
        f'<span class="when">{when}</span><div>{body}</div></div>'
    )


async def broadcast(fragments):
    payload = json.dumps({"fragments": fragments})
    stale = []
    for queue in clients:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            stale.append(queue)
    for queue in stale:
        clients.discard(queue)


@app.get("/")
async def index():
    return PAGE, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.get("/health")
async def health():
    return {"status": "ok", "clients": len(clients), "history": len(history)}


@app.websocket("/ws")
async def chat_socket():
    queue = asyncio.Queue(maxsize=200)
    clients.add(queue)
    await websocket.send(json.dumps({"fragments": list(history)}))

    async def pump():
        while True:
            await websocket.send(await queue.get())

    sender = asyncio.create_task(pump())
    try:
        while True:
            raw = await websocket.receive()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            name = str(data.get("name", "")).strip()[:MAX_NAME_LENGTH] or "Guest"
            text = str(data.get("text", "")).strip()[:MAX_MESSAGE_LENGTH]
            if not text:
                continue
            fragment = render_message_fragment(name, text, datetime.now(timezone.utc))
            history.append(fragment)
            del history[:-HISTORY_SIZE]
            await broadcast([fragment])
    except asyncio.CancelledError:
        pass
    finally:
        sender.cancel()
        clients.discard(queue)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))