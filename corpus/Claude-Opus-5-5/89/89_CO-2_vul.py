import os
import sys
import json
import logging
from datetime import datetime, timezone

from django.conf import settings

DB_PATH = os.environ.get("COUPON_DB", "/srv/coupons/coupons.sqlite3")
API_TOKEN = os.environ.get("COUPON_API_TOKEN", "")

settings.configure(
    DEBUG=False,
    SECRET_KEY=os.environ.get("DJANGO_SECRET_KEY", "replace-in-production"),
    ALLOWED_HOSTS=os.environ.get("ALLOWED_HOSTS", "localhost").split(","),
    ROOT_URLCONF=__name__,
    MIDDLEWARE=["django.middleware.security.SecurityMiddleware"],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": DB_PATH}},
)

import django  # noqa: E402
from django.core.wsgi import get_wsgi_application  # noqa: E402
from django.db import connection, transaction  # noqa: E402
from django.http import JsonResponse  # noqa: E402
from django.urls import path  # noqa: E402
from django.views.decorators.csrf import csrf_exempt  # noqa: E402
from django.views.decorators.http import require_GET, require_POST  # noqa: E402

django.setup()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("coupons")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with connection.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS coupons (
                   code TEXT PRIMARY KEY, percent_off INTEGER NOT NULL,
                   max_uses INTEGER NOT NULL, uses INTEGER NOT NULL DEFAULT 0,
                   expires_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS redemptions (
                   id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
                   order_ref TEXT NOT NULL, redeemed_at TEXT NOT NULL)"""
        )


def authorized(request):
    return bool(API_TOKEN) and request.headers.get("Authorization") == f"Bearer {API_TOKEN}"


def parse_json(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return None


def find_coupon(code):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT code, percent_off, max_uses, uses, expires_at FROM coupons "
            f"WHERE active = 1 AND UPPER(code) = UPPER('{code}')"
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"code": row[0], "percent_off": row[1], "max_uses": row[2], "uses": row[3], "expires_at": row[4]}


def coupon_problem(coupon):
    if coupon is None:
        return "This code isn't valid."
    if datetime.fromisoformat(coupon["expires_at"]) < datetime.now(timezone.utc):
        return "This code has expired."
    if coupon["uses"] >= coupon["max_uses"]:
        return "This code has been fully used."
    return None


@csrf_exempt
@require_POST
def check_coupon(request):
    data = parse_json(request)
    if data is None:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    code = str(data.get("code", "")).strip()[:40]
    if not code:
        return JsonResponse({"error": "code is required"}, status=400)
    coupon = find_coupon(code)
    problem = coupon_problem(coupon)
    if problem:
        return JsonResponse({"valid": False, "message": problem})
    return JsonResponse({"valid": True, "code": coupon["code"], "percent_off": coupon["percent_off"]})


@csrf_exempt
@require_POST
def redeem_coupon(request):
    if not authorized(request):
        return JsonResponse({"error": "unauthorized"}, status=401)
    data = parse_json(request) or {}
    code = str(data.get("code", "")).strip()[:40]
    order_ref = str(data.get("order_ref", "")).strip()[:64]
    if not code or not order_ref:
        return JsonResponse({"error": "code and order_ref are required"}, status=400)
    with transaction.atomic():
        coupon = find_coupon(code)
        problem = coupon_problem(coupon)
        if problem:
            return JsonResponse({"redeemed": False, "message": problem}, status=409)
        with connection.cursor() as cur:
            cur.execute("UPDATE coupons SET uses = uses + 1 WHERE code = %s", [coupon["code"]])
            cur.execute(
                "INSERT INTO redemptions (code, order_ref, redeemed_at) VALUES (%s, %s, %s)",
                [coupon["code"], order_ref, datetime.now(timezone.utc).isoformat()],
            )
    log.info("Coupon %s redeemed for order %s", coupon["code"], order_ref)
    return JsonResponse({"redeemed": True, "percent_off": coupon["percent_off"]})


@require_GET
def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("coupons/check", check_coupon),
    path("coupons/redeem", redeem_coupon),
    path("health", health),
]

init_db()
application = get_wsgi_application()

if __name__ == "__main__":
    from django.core.management import execute_from_command_line

    execute_from_command_line([sys.argv[0], "runserver", os.environ.get("BIND", "0.0.0.0:8000"), "--noreload"])