import os
import hmac
import json
import hashlib
import logging
from collections import deque
from datetime import datetime, timezone
from html import escape

from fastapi import HTTPException, Request
from nicegui import app, ui

WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "").encode()
MAX_EVENTS = 40
TRACKED_BRANCHES = set(filter(None, os.environ.get("TRACKED_BRANCHES", "main,release").split(",")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("deploy-board")

events = deque(maxlen=MAX_EVENTS)


def verify_signature(body, header):
    if not WEBHOOK_SECRET or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def summarize_push(payload):
    ref = payload.get("ref", "")
    branch = ref.removeprefix("refs/heads/")
    commits = payload.get("commits", [])[-10:]
    return {
        "repo": payload.get("repository", {}).get("full_name", "unknown"),
        "branch": branch,
        "pusher": payload.get("pusher", {}).get("name", "unknown"),
        "received": datetime.now(timezone.utc),
        "commits": [
            {
                "sha": str(c.get("id", ""))[:7],
                "author": c.get("author", {}).get("name", "unknown"),
                "message": str(c.get("message", "")),
                "url": c.get("url", ""),
            }
            for c in commits
        ],
    }


def format_commit_html(commit):
    first_line, _, rest = str(commit["message"]).partition("\n")
    if len(first_line) > 200:
        first_line = first_line[:200] + "…"
    details = escape(rest.strip()[:2000]).replace("\n", "<br>")
    sha = "".join(ch for ch in str(commit["sha"]) if ch in "0123456789abcdef")
    author = escape(str(commit["author"]))
    body = f"<div class='commit-details'>{details}</div>" if details else ""
    return (
        f"<div class='commit'><code>{sha}</code> "
        f"<strong>{escape(first_line)}</strong> <span class='who'>by {author}</span>{body}</div>"
    )


@app.post("/webhooks/github")
async def github_webhook(request: Request):
    body = await request.body()
    if not verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="bad signature")
    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return {"ok": True}
    if event != "push":
        return {"ignored": event}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")
    summary = summarize_push(payload)
    if TRACKED_BRANCHES and summary["branch"] not in TRACKED_BRANCHES:
        return {"ignored": summary["branch"]}
    events.appendleft(summary)
    log.info("Push to %s/%s with %d commit(s)", summary["repo"], summary["branch"], len(summary["commits"]))
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok", "events": len(events)}


@ui.page("/")
def board():
    ui.add_head_html("""<style>
      .commit { padding: .3rem 0; border-bottom: 1px solid #eee; }
      .commit code { color: #666; }
      .commit .who { color: #888; font-size: .85rem; }
      .commit-details { color: #555; font-size: .85rem; margin-left: 4.5rem; }
    </style>""")
    ui.label("Deploy board").classes("text-2xl font-bold")
    ui.label("Recent pushes to tracked branches").classes("text-gray-500")
    container = ui.column().classes("w-full")

    def refresh():
        container.clear()
        with container:
            if not events:
                ui.label("No pushes received yet.")
                return
            for push in list(events):
                with ui.card().classes("w-full"):
                    ui.label(f"{push['repo']} · {push['branch']}").classes("font-semibold")
                    ui.label(
                        f"Pushed by {push['pusher']} at {push['received']:%Y-%m-%d %H:%M UTC}"
                    ).classes("text-sm text-gray-500")
                    for commit in push["commits"]:
                        ui.html(format_commit_html(commit))

    refresh()
    ui.timer(15.0, refresh)


if __name__ in {"__main__", "__mp_main__"}:
    if not WEBHOOK_SECRET:
        log.warning("GITHUB_WEBHOOK_SECRET is not set; all webhooks will be rejected")
    ui.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), title="Deploy board", reload=False)