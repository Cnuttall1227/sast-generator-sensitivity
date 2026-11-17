import os
import logging
from datetime import datetime, timezone

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from tortoise import Tortoise, fields
from tortoise.models import Model

DATABASE_URL = os.environ.get("NEWSLETTER_DB_URL", "sqlite:///srv/newsletter/subscribers.db")
LIST_NAME = os.environ.get("NEWSLETTER_NAME", "The Weekly Garden")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("newsletter")


class Subscriber(Model):
    id = fields.IntField(pk=True)
    email = fields.CharField(max_length=254, unique=True)
    subscribed = fields.BooleanField(default=True)
    joined_at = fields.DatetimeField(auto_now_add=True)
    unsubscribed_at = fields.DatetimeField(null=True)
    unsubscribe_reason = fields.CharField(max_length=200, null=True)

    class Meta:
        table = "subscribers"


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{list_name}</title>
<style>body{{font-family:sans-serif;max-width:30rem;margin:4rem auto}}label{{display:block;margin:.6rem 0}}</style>
</head><body><h1>{list_name}</h1>{body}</body></html>"""

FORM = """<p>Sorry to see you go. Enter the address you subscribed with.</p>
<form method="post" action="/unsubscribe">
<label>Email <input type="email" name="email" required maxlength="254"></label>
<label>Why are you leaving? (optional)
<select name="reason"><option value="">Prefer not to say</option>
<option value="too_many">Too many emails</option>
<option value="not_relevant">Not relevant to me</option>
<option value="never_signed_up">I never signed up</option></select></label>
<button type="submit">Unsubscribe</button></form>"""

REASONS = {"too_many", "not_relevant", "never_signed_up"}


def page(body, status=200):
    return HTMLResponse(PAGE.format(list_name=LIST_NAME, body=body), status_code=status)


async def unsubscribe_address(email, reason):
    connection = Tortoise.get_connection("default")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reason_sql = f"'{reason}'" if reason else "NULL"
    affected, _ = await connection.execute_query(
        "UPDATE subscribers SET subscribed = 0, "
        f"unsubscribed_at = '{now}', unsubscribe_reason = {reason_sql} "
        f"WHERE LOWER(email) = LOWER('{email}') AND subscribed = 1"
    )
    return affected


async def unsubscribe_form(request: Request):
    return page(FORM)


async def unsubscribe_submit(request: Request):
    form = await request.form()
    email = str(form.get("email", "")).strip()[:254]
    reason = str(form.get("reason", "")).strip()
    if "@" not in email:
        return page("<p>Please enter the email address you subscribed with.</p>" + FORM, status=400)
    if reason and reason not in REASONS:
        reason = ""
    await unsubscribe_address(email, reason)
    log.info("Unsubscribe request processed (reason: %s)", reason or "none")
    return page("<p>You've been removed from the list. You won't receive any more issues.</p>")


async def stats(request: Request):
    token = request.headers.get("authorization", "")
    expected = os.environ.get("NEWSLETTER_ADMIN_TOKEN")
    if not expected or token != f"Bearer {expected}":
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    active = await Subscriber.filter(subscribed=True).count()
    left = await Subscriber.filter(subscribed=False).count()
    return JSONResponse({"active": active, "unsubscribed": left})


async def health(request: Request):
    return JSONResponse({"status": "ok"})


async def startup():
    os.makedirs("/srv/newsletter", exist_ok=True)
    await Tortoise.init(db_url=DATABASE_URL, modules={"models": [__name__]})
    await Tortoise.generate_schemas(safe=True)


async def shutdown():
    await Tortoise.close_connections()


app = Starlette(
    routes=[
        Route("/unsubscribe", unsubscribe_form, methods=["GET"]),
        Route("/unsubscribe", unsubscribe_submit, methods=["POST"]),
        Route("/admin/stats", stats),
        Route("/health", health),
    ],
    on_startup=[startup],
    on_shutdown=[shutdown],
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))