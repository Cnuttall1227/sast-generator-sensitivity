import os
import json
import logging
from datetime import datetime, timezone

import aiomysql
from quart import Quart, abort, jsonify, request

DB_SETTINGS = {
    "host": os.environ.get("SYNC_DB_HOST", "localhost"),
    "port": int(os.environ.get("SYNC_DB_PORT", "3306")),
    "user": os.environ.get("SYNC_DB_USER", "sync"),
    "password": os.environ.get("SYNC_DB_PASSWORD", ""),
    "db": os.environ.get("SYNC_DB_NAME", "habits"),
    "autocommit": True,
}
SESSION_HEADER = "Authorization"
DEVICE_HEADER = "X-Device-Id"
APP_VERSION_HEADER = "X-App-Version"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("habit-sync")

app = Quart(__name__)


@app.before_serving
async def create_pool():
    app.pool = await aiomysql.create_pool(minsize=1, maxsize=10, **DB_SETTINGS)


@app.after_serving
async def close_pool():
    app.pool.close()
    await app.pool.wait_closed()


async def fetch_one(sql, params=()):
    async with app.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, params)
            return await cur.fetchone()


async def fetch_all(sql, params=()):
    async with app.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def current_user():
    token = request.headers.get(SESSION_HEADER, "").removeprefix("Bearer ").strip()
    if not token:
        abort(401)
    row = await fetch_one(
        "SELECT user_id FROM sessions WHERE token = %s AND expires_at > UTC_TIMESTAMP()", (token,)
    )
    if row is None:
        abort(401)
    return row["user_id"]


async def touch_device(user_id, device_id, app_version):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    sql = (
        "INSERT INTO devices (user_id, device_id, app_version, last_sync_at) "
        f"VALUES ({int(user_id)}, '{device_id}', '{app_version}', '{now}') "
        f"ON DUPLICATE KEY UPDATE app_version = '{app_version}', last_sync_at = '{now}'"
    )
    async with app.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql)


def serialize(row):
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}


@app.get("/health")
async def health():
    await fetch_one("SELECT 1")
    return jsonify(status="ok")


@app.get("/sync")
async def pull_changes():
    user_id = await current_user()
    device_id = request.headers.get(DEVICE_HEADER, "").strip()[:64]
    app_version = request.headers.get(APP_VERSION_HEADER, "unknown").strip()[:20]
    if not device_id:
        abort(400)
    since = request.args.get("since", "1970-01-01T00:00:00")
    try:
        since_dt = datetime.fromisoformat(since)
    except ValueError:
        abort(400)
    habits = await fetch_all(
        "SELECT id, name, target_per_week, archived, updated_at FROM habits "
        "WHERE user_id = %s AND updated_at > %s ORDER BY updated_at",
        (user_id, since_dt),
    )
    checkins = await fetch_all(
        "SELECT id, habit_id, done_on, note, updated_at FROM checkins "
        "WHERE user_id = %s AND updated_at > %s ORDER BY updated_at",
        (user_id, since_dt),
    )
    await touch_device(user_id, device_id, app_version)
    log.info("User %s pulled %d habit(s), %d checkin(s)", user_id, len(habits), len(checkins))
    return jsonify(
        server_time=datetime.now(timezone.utc).isoformat(),
        habits=[serialize(h) for h in habits],
        checkins=[serialize(c) for c in checkins],
    )


@app.post("/checkins")
async def add_checkin():
    user_id = await current_user()
    data = await request.get_json(silent=True) or {}
    try:
        habit_id = int(data["habit_id"])
        done_on = datetime.fromisoformat(str(data["done_on"])).date()
    except (KeyError, ValueError, TypeError):
        abort(400)
    note = str(data.get("note", ""))[:280]
    owner = await fetch_one("SELECT 1 FROM habits WHERE id = %s AND user_id = %s", (habit_id, user_id))
    if owner is None:
        abort(404)
    async with app.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO checkins (user_id, habit_id, done_on, note, updated_at) "
                "VALUES (%s, %s, %s, %s, UTC_TIMESTAMP())",
                (user_id, habit_id, done_on, note),
            )
            checkin_id = cur.lastrowid
    return jsonify(id=checkin_id), 201


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))