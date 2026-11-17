import os
import json
import logging

import pymysql
import pymysql.cursors
import tornado.ioloop
import tornado.web

DB_SETTINGS = {
    "host": os.environ.get("STORES_DB_HOST", "localhost"),
    "user": os.environ.get("STORES_DB_USER", "stores"),
    "password": os.environ.get("STORES_DB_PASSWORD", ""),
    "database": os.environ.get("STORES_DB_NAME", "stores"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}
REGION_COOKIE = "preferred_region"
DEFAULT_REGION = "midwest"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("store-locator")


def connect():
    return pymysql.connect(**DB_SETTINGS)


def list_regions():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT slug, name FROM regions ORDER BY name")
        return cur.fetchall()


def stores_in_region(region, open_now):
    sql = (
        "SELECT s.id, s.name, s.street, s.city, s.phone, s.opens_at, s.closes_at "
        "FROM stores s JOIN regions r ON r.id = s.region_id "
        "WHERE r.slug = %s AND s.active = 1"
    )
    if open_now:
        sql += " AND CURTIME() BETWEEN s.opens_at AND s.closes_at"
    sql += " ORDER BY s.city, s.name"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (region,))
        rows = cur.fetchall()
    for row in rows:
        row["opens_at"] = str(row["opens_at"])[:5]
        row["closes_at"] = str(row["closes_at"])[:5]
    return rows


def store_detail(store_id):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, street, city, phone, opens_at, closes_at, services "
            "FROM stores WHERE id = %s AND active = 1",
            (store_id,),
        )
        row = cur.fetchone()
    if row:
        row["opens_at"] = str(row["opens_at"])[:5]
        row["closes_at"] = str(row["closes_at"])[:5]
        row["services"] = json.loads(row["services"] or "[]")
    return row


class JsonHandler(tornado.web.RequestHandler):
    def write_json(self, payload, status=200):
        self.set_status(status)
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(payload))

    def write_error(self, status_code, **kwargs):
        self.write_json({"error": self._reason}, status_code)


class RegionsHandler(JsonHandler):
    def get(self):
        self.write_json({"regions": list_regions(), "selected": self.get_cookie(REGION_COOKIE, DEFAULT_REGION)})


class PreferenceHandler(JsonHandler):
    def post(self):
        try:
            body = json.loads(self.request.body or b"{}")
        except json.JSONDecodeError:
            raise tornado.web.HTTPError(400, reason="invalid JSON")
        region = str(body.get("region", "")).strip()
        if region not in {r["slug"] for r in list_regions()}:
            raise tornado.web.HTTPError(400, reason="unknown region")
        self.set_cookie(REGION_COOKIE, region, expires_days=180, httponly=True, samesite="Lax")
        self.write_json({"selected": region})


class StoresHandler(JsonHandler):
    def get(self):
        region = self.get_cookie(REGION_COOKIE, DEFAULT_REGION)
        open_now = self.get_argument("open_now", "false").lower() == "true"
        stores = stores_in_region(region, open_now)
        log.info("Listed %d store(s) in %s", len(stores), region)
        self.write_json({"region": region, "open_now": open_now, "stores": stores})


class StoreHandler(JsonHandler):
    def get(self, store_id):
        store = store_detail(int(store_id))
        if store is None:
            raise tornado.web.HTTPError(404, reason="store not found")
        self.write_json(store)


class HealthHandler(JsonHandler):
    def get(self):
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        self.write_json({"status": "ok"})


def make_app():
    return tornado.web.Application([
        (r"/api/regions", RegionsHandler),
        (r"/api/preferences/region", PreferenceHandler),
        (r"/api/stores", StoresHandler),
        (r"/api/stores/(\d+)", StoreHandler),
        (r"/health", HealthHandler),
    ])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8888"))
    make_app().listen(port)
    log.info("Store locator listening on port %d", port)
    tornado.ioloop.IOLoop.current().start()