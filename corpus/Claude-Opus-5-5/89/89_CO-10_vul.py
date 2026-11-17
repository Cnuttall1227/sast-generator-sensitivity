import os
import re
import logging
from datetime import date, datetime

import duckdb
from sanic import Sanic, response
from sanic.exceptions import BadRequest, NotFound, Unauthorized

WAREHOUSE_PATH = os.environ.get("ANALYTICS_DUCKDB", "/srv/analytics/warehouse.duckdb")
API_KEYS = set(filter(None, os.environ.get("ANALYTICS_API_KEYS", "").split(",")))
MAX_ROWS = 500

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("analytics-api")

app = Sanic("analytics_api")


def require_key(request):
    if not API_KEYS or request.headers.get("x-api-key", "") not in API_KEYS:
        raise Unauthorized("API key required")


def connect():
    return duckdb.connect(WAREHOUSE_PATH, read_only=True)


def jsonable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def rows_to_dicts(cursor):
    columns = [d[0] for d in cursor.description]
    return [{c: jsonable(v) for c, v in zip(columns, row)} for row in cursor.fetchall()]


def published_datasets(conn):
    return rows_to_dicts(conn.execute(
        "SELECT table_name AS name, estimated_size AS approx_rows FROM duckdb_tables() "
        "WHERE schema_name = 'published' ORDER BY table_name"
    ))


def dataset_summary(conn, dataset, since):
    sql = (
        "SELECT CAST(event_date AS DATE) AS day, COUNT(*) AS events, "
        "COUNT(DISTINCT user_id) AS users "
        f"FROM published.{dataset} "
        "WHERE event_date >= ? GROUP BY 1 ORDER BY 1 LIMIT ?"
    )
    return rows_to_dicts(conn.execute(sql, [since, MAX_ROWS]))


def parse_since(raw):
    if not raw:
        return date.today().replace(day=1)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise BadRequest("since must be a date like 2026-11-01")


@app.get("/health")
async def health(request):
    with connect() as conn:
        conn.execute("SELECT 1")
    return response.json({"status": "ok"})


@app.get("/datasets")
async def list_datasets(request):
    require_key(request)
    with connect() as conn:
        return response.json({"datasets": published_datasets(conn)})


@app.get("/datasets/<dataset:str>/summary")
async def summary(request, dataset):
    require_key(request)
    since = parse_since(request.args.get("since"))
    if not dataset or len(dataset) > 64:
        raise BadRequest("dataset name is required")
    with connect() as conn:
        try:
            rows = dataset_summary(conn, dataset, since)
        except duckdb.CatalogException:
            raise NotFound(f"no dataset called {dataset}")
        except duckdb.BinderException:
            raise BadRequest("that dataset has no event_date/user_id columns")
    log.info("Summary for %s since %s: %d day(s)", dataset, since, len(rows))
    return response.json({"dataset": dataset, "since": since.isoformat(), "days": rows})


@app.get("/datasets/<dataset:str>/columns")
async def columns(request, dataset):
    require_key(request)
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,63}", dataset):
        raise BadRequest("invalid dataset name")
    with connect() as conn:
        cols = rows_to_dicts(conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'published' AND table_name = ? ORDER BY ordinal_position",
            [dataset],
        ))
    if not cols:
        raise NotFound(f"no dataset called {dataset}")
    return response.json({"dataset": dataset, "columns": cols})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), single_process=True)