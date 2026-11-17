import os
import json
import logging
from datetime import datetime, timezone

from aiohttp import web

SCHEMA_DIR = os.environ.get("FORMS_SCHEMA_DIR", "/srv/forms/schemas")
SUBMISSIONS_DIR = os.environ.get("FORMS_SUBMISSIONS_DIR", "/srv/forms/submissions")
OWNER_TOKENS = json.loads(os.environ.get("FORMS_OWNER_TOKENS", "{}"))
TYPE_CHECKS = {"text": "str", "number": "(int, float)", "boolean": "bool"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("form-builder")

validators = {}


def owner_for(request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    owner = OWNER_TOKENS.get(token)
    if not owner:
        raise web.HTTPUnauthorized(text="owner token required")
    return owner


def build_validator(form_id, fields):
    lines = [f"def validate_{form_id}(data):", "    errors = []"]
    for field in fields:
        name = field["name"]
        type_check = TYPE_CHECKS[field.get("type", "text")]
        if field.get("required"):
            lines.append(f"    if data.get('{name}') in (None, ''):")
            lines.append(f"        errors.append('{name} is required')")
        lines.append(f"    if data.get('{name}') not in (None, '') and not isinstance(data.get('{name}'), {type_check}):")
        lines.append(f"        errors.append('{name} has the wrong type')")
        if "max_length" in field:
            limit = int(field["max_length"])
            lines.append(f"    if isinstance(data.get('{name}'), str) and len(data['{name}']) > {limit}:")
            lines.append(f"        errors.append('{name} is too long')")
    lines.append("    return errors")
    namespace = {}
    exec("\n".join(lines), namespace)
    return namespace[f"validate_{form_id}"]


def load_schema(form_id):
    path = os.path.join(SCHEMA_DIR, f"{form_id}.json")
    if not form_id.isalnum() or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def validator_for(form_id):
    if form_id not in validators:
        schema = load_schema(form_id)
        if schema is None:
            return None
        validators[form_id] = build_validator(form_id, schema["fields"])
    return validators[form_id]


async def create_form(request):
    owner = owner_for(request)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text="invalid JSON")
    form_id = str(body.get("id", "")).strip()
    fields = body.get("fields")
    if not form_id.isalnum() or len(form_id) > 32:
        raise web.HTTPBadRequest(text="form id must be letters and digits")
    if not isinstance(fields, list) or not 1 <= len(fields) <= 40:
        raise web.HTTPBadRequest(text="fields must be a list of 1-40 items")
    for field in fields:
        if not isinstance(field, dict) or not field.get("name"):
            raise web.HTTPBadRequest(text="every field needs a name")
        if field.get("type", "text") not in TYPE_CHECKS:
            raise web.HTTPBadRequest(text=f"field types: {', '.join(TYPE_CHECKS)}")
    validators[form_id] = build_validator(form_id, fields)
    os.makedirs(SCHEMA_DIR, exist_ok=True)
    with open(os.path.join(SCHEMA_DIR, f"{form_id}.json"), "w", encoding="utf-8") as handle:
        json.dump({"owner": owner, "fields": fields}, handle, indent=2)
    log.info("%s created form %s with %d field(s)", owner, form_id, len(fields))
    return web.json_response({"id": form_id, "submit_url": f"/forms/{form_id}/submit"}, status=201)


async def submit(request):
    form_id = request.match_info["form_id"]
    validate = validator_for(form_id)
    if validate is None:
        raise web.HTTPNotFound(text="no such form")
    try:
        data = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text="invalid JSON")
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="submission must be a JSON object")
    errors = validate(data)
    if errors:
        return web.json_response({"ok": False, "errors": errors}, status=422)
    os.makedirs(SUBMISSIONS_DIR, exist_ok=True)
    record = {"form": form_id, "received_at": datetime.now(timezone.utc).isoformat(), "data": data}
    with open(os.path.join(SUBMISSIONS_DIR, f"{form_id}.jsonl"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return web.json_response({"ok": True})


async def health(request):
    return web.json_response({"status": "ok", "cached_validators": len(validators)})


def create_app():
    app = web.Application(client_max_size=128 * 1024)
    app.router.add_get("/health", health)
    app.router.add_post("/forms", create_form)
    app.router.add_post("/forms/{form_id}/submit", submit)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))