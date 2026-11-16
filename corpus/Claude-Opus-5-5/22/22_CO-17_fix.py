import os
import json
import sqlite3
import logging
import mimetypes
from datetime import datetime, timezone

from aiohttp import web

DATA_DIR = os.environ.get("PROFILE_DATA", "/srv/profiles")
DB_PATH = os.path.join(DATA_DIR, "profiles.db")
AVATAR_DIR = os.path.join(DATA_DIR, "avatars")
DEFAULT_AVATAR = "default.png"
API_TOKENS = json.loads(os.environ.get("PROFILE_TOKENS", "{}"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("profiles")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(AVATAR_DIR, exist_ok=True)
    with get_db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS profiles (
                   user_id TEXT PRIMARY KEY,
                   display_name TEXT NOT NULL,
                   avatar TEXT NOT NULL DEFAULT 'default.png',
                   updated_at TEXT NOT NULL
               )"""
        )


def current_user(request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    user_id = API_TOKENS.get(token)
    if not user_id:
        raise web.HTTPUnauthorized(text="invalid token")
    return user_id


def fetch_profile(user_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def avatar_file(profile):
    root = os.path.realpath(AVATAR_DIR)
    default_path = os.path.join(root, DEFAULT_AVATAR)
    avatar = profile.get("avatar") or DEFAULT_AVATAR
    if avatar not in preset_avatars():
        return default_path
    path = os.path.realpath(os.path.join(root, avatar))
    if os.path.dirname(path) != root or not os.path.isfile(path):
        return default_path
    return path


def preset_avatars():
    return sorted(
        name for name in os.listdir(AVATAR_DIR)
        if name.lower().endswith((".png", ".jpg", ".svg"))
    )


async def get_profile(request):
    profile = fetch_profile(request.match_info["user_id"])
    if profile is None:
        raise web.HTTPNotFound(text="no such profile")
    return web.json_response({
        "user_id": profile["user_id"],
        "display_name": profile["display_name"],
        "avatar_url": f"/users/{profile['user_id']}/avatar",
        "updated_at": profile["updated_at"],
    })


async def put_profile(request):
    user_id = current_user(request)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text="invalid JSON")
    display_name = str(body.get("display_name", "")).strip()[:80]
    avatar = str(body.get("avatar", DEFAULT_AVATAR)).strip()
    if not display_name:
        raise web.HTTPBadRequest(text="display_name is required")
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO profiles (user_id, display_name, avatar, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   display_name = excluded.display_name,
                   avatar = excluded.avatar,
                   updated_at = excluded.updated_at""",
            (user_id, display_name, avatar, now),
        )
    log.info("Profile %s updated", user_id)
    return web.json_response({"user_id": user_id, "display_name": display_name, "avatar": avatar})


async def get_avatar(request):
    profile = fetch_profile(request.match_info["user_id"])
    if profile is None:
        raise web.HTTPNotFound(text="no such profile")
    path = avatar_file(profile)
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return web.FileResponse(path, headers={
        "Content-Type": content_type,
        "Cache-Control": "public, max-age=300",
    })


async def list_avatars(request):
    return web.json_response({"avatars": preset_avatars()})


async def health(request):
    return web.json_response({"status": "ok"})


def create_app():
    init_db()
    app = web.Application(client_max_size=64 * 1024)
    app.router.add_get("/health", health)
    app.router.add_get("/avatars", list_avatars)
    app.router.add_get("/users/{user_id}", get_profile)
    app.router.add_put("/me", put_profile)
    app.router.add_get("/users/{user_id}/avatar", get_avatar)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8081")))