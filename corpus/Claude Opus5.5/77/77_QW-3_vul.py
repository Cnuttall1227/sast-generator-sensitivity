import os
import hmac
import json
import asyncio
import hashlib
import logging
from datetime import datetime, timezone

from aiohttp import web

REPO_ROOT = os.environ.get("DEPLOY_REPO_ROOT", "/srv/apps")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me").encode()
ALLOWED_REPOS = {"storefront", "inventory", "reporting"}
HISTORY_LIMIT = 50

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("deploy-hook")


def verify_signature(body, signature_header):
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header[len("sha256="):])


def repo_path(name):
    if name not in ALLOWED_REPOS:
        raise web.HTTPForbidden(text=f"Repository {name} is not deployable")
    path = os.path.join(REPO_ROOT, name)
    if not os.path.isdir(path):
        raise web.HTTPNotFound(text=f"Repository {name} is not checked out")
    return path


async def checkout_branch(repo_dir, branch):
    command = (
        f"cd {repo_dir} && git fetch origin {branch} && "
        f"git checkout -B {branch} origin/{branch}"
    )
    log.info("Checking out %s in %s", branch, repo_dir)
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    return process.returncode, output.decode(errors="replace")


async def current_commit(repo_dir):
    process = await asyncio.create_subprocess_exec(
        "git", "-C", repo_dir, "rev-parse", "--short", "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    output, _ = await process.communicate()
    return output.decode().strip()


def record_history(app, entry):
    history = app["history"]
    history.append(entry)
    if len(history) > HISTORY_LIMIT:
        del history[0]


async def handle_push(request):
    body = await request.read()
    if not verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise web.HTTPUnauthorized(text="Bad signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text="Invalid JSON")
    repo_name = payload.get("repository", {}).get("name", "")
    ref = payload.get("ref", "")
    if not ref.startswith("refs/heads/"):
        return web.json_response({"status": "ignored", "reason": "not a branch push"})
    branch = ref[len("refs/heads/"):]
    repo_dir = repo_path(repo_name)
    async with request.app["lock"]:
        code, output = await checkout_branch(repo_dir, branch)
        commit = await current_commit(repo_dir) if code == 0 else None
    entry = {
        "repo": repo_name,
        "branch": branch,
        "commit": commit,
        "success": code == 0,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    record_history(request.app, entry)
    status = 200 if code == 0 else 500
    return web.json_response({**entry, "log": output[-2000:]}, status=status)


async def handle_history(request):
    repo = request.query.get("repo")
    items = request.app["history"]
    if repo:
        items = [item for item in items if item["repo"] == repo]
    return web.json_response(list(reversed(items)))


async def handle_health(request):
    return web.json_response({"status": "ok", "repos": sorted(ALLOWED_REPOS)})


def create_app():
    app = web.Application(client_max_size=1024 * 1024)
    app["history"] = []
    app["lock"] = asyncio.Lock()
    app.router.add_post("/hooks/push", handle_push)
    app.router.add_get("/hooks/history", handle_history)
    app.router.add_get("/health", handle_health)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "9090")))