import os
import json
import logging
from datetime import date

import asyncpg
from aiohttp import web

DATABASE_URL = os.environ.get("CLINIC_DATABASE_URL", "postgresql://clinic:clinic@localhost/clinic")
STAFF_TOKENS = json.loads(os.environ.get("CLINIC_STAFF_TOKENS", "{}"))
UPDATABLE_HINT = ["first_name", "last_name", "phone", "email", "preferred_vet", "notes"]
UPDATABLE_COLUMNS = {
    "first_name": "first_name",
    "last_name": "last_name",
    "phone": "phone",
    "email": "email",
    "preferred_vet": "preferred_vet",
    "notes": "notes",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pet-clinic")


def staff_member(request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    member = STAFF_TOKENS.get(token)
    if not member:
        raise web.HTTPUnauthorized(text="staff token required")
    return member


def record_to_json(record):
    data = dict(record)
    for key, value in data.items():
        if isinstance(value, date):
            data[key] = value.isoformat()
    return data


async def update_owner_fields(pool, owner_id, changes):
    if not changes:
        raise web.HTTPBadRequest(text="no fields to update")
    unknown = [key for key in changes if key not in UPDATABLE_COLUMNS]
    if unknown:
        raise web.HTTPBadRequest(
            text=f"fields that can be updated: {', '.join(UPDATABLE_COLUMNS)}"
        )
    assignments = []
    values = []
    for index, (field, value) in enumerate(changes.items(), start=1):
        assignments.append(f"{UPDATABLE_COLUMNS[field]} = ${index}")
        values.append(None if value is None else str(value)[:500])
    values.append(int(owner_id))
    sql = (
        f"UPDATE owners SET {', '.join(assignments)}, updated_at = now() "
        f"WHERE id = ${len(values)} RETURNING id, first_name, last_name, phone, email, preferred_vet, notes"
    )
    async with pool.acquire() as conn:
        return await conn.fetchrow(sql, *values)


async def get_owner(request):
    staff_member(request)
    owner_id = int(request.match_info["owner_id"])
    async with request.app["pool"].acquire() as conn:
        owner = await conn.fetchrow(
            "SELECT id, first_name, last_name, phone, email, preferred_vet, notes FROM owners WHERE id = $1",
            owner_id,
        )
        if owner is None:
            raise web.HTTPNotFound(text="owner not found")
        pets = await conn.fetch(
            "SELECT id, name, species, born_on FROM pets WHERE owner_id = $1 ORDER BY name", owner_id
        )
    return web.json_response({**record_to_json(owner), "pets": [record_to_json(p) for p in pets]})


async def patch_owner(request):
    member = staff_member(request)
    owner_id = int(request.match_info["owner_id"])
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text="invalid JSON")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="body must be a JSON object")
    updated = await update_owner_fields(request.app["pool"], owner_id, body)
    if updated is None:
        raise web.HTTPNotFound(text="owner not found")
    log.info("%s updated owner %d (%s)", member, owner_id, ", ".join(body))
    return web.json_response(record_to_json(updated))


async def search_owners(request):
    staff_member(request)
    phone = request.query.get("phone", "").strip()
    if len(phone) < 4:
        raise web.HTTPBadRequest(text="search with at least 4 digits of a phone number")
    async with request.app["pool"].acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, first_name, last_name, phone FROM owners WHERE phone LIKE '%' || $1 || '%' "
            "ORDER BY last_name LIMIT 20",
            phone,
        )
    return web.json_response({"owners": [record_to_json(r) for r in rows], "editable_fields": UPDATABLE_HINT})


async def health(request):
    async with request.app["pool"].acquire() as conn:
        await conn.execute("SELECT 1")
    return web.json_response({"status": "ok"})


async def on_startup(app):
    app["pool"] = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)


async def on_cleanup(app):
    await app["pool"].close()


def create_app():
    app = web.Application(client_max_size=64 * 1024)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/health", health)
    app.router.add_get("/owners", search_owners)
    app.router.add_get(r"/owners/{owner_id:\d+}", get_owner)
    app.router.add_patch(r"/owners/{owner_id:\d+}", patch_owner)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))