import os
import logging
from datetime import date
from decimal import Decimal
from typing import Optional

import psycopg2
import psycopg2.extras
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query

DATABASE_URL = os.environ.get("ORDERS_DATABASE_URL", "postgresql://orders:orders@localhost/orders")
API_KEYS = set(filter(None, os.environ.get("ORDERS_API_KEYS", "").split(",")))
PAGE_SIZE_MAX = 100
SORT_COLUMNS = {
    "placed_on": "o.placed_on",
    "total": "o.total",
    "status": "o.status",
    "order_number": "o.order_number",
    "line_items": "line_items",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("orders-api")

app = FastAPI(title="Wholesale orders API")


def get_conn():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


def require_key(x_api_key: str = Header(default="")):
    if not API_KEYS or x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="invalid API key")
    return x_api_key


def serialize(row):
    out = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            out[key] = str(value)
        elif isinstance(value, date):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def list_orders(conn, customer_id, status, sort, direction, limit, offset):
    sort_column = SORT_COLUMNS.get(sort)
    if sort_column is None:
        raise HTTPException(status_code=400, detail=f"sort must be one of: {', '.join(SORT_COLUMNS)}")
    direction = direction.lower()
    if direction not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="direction must be asc or desc")
    conditions = ["o.customer_id = %s"]
    params = [customer_id]
    if status:
        conditions.append("o.status = %s")
        params.append(status)
    sql = (
        "SELECT o.id, o.order_number, o.status, o.placed_on, o.total, "
        "COUNT(i.id) AS line_items "
        "FROM orders o LEFT JOIN order_items i ON i.order_id = o.id "
        f"WHERE {' AND '.join(conditions)} "
        "GROUP BY o.id "
        f"ORDER BY {sort_column} {direction.upper()}, o.id {direction.upper()} "
        "LIMIT %s OFFSET %s"
    )
    params.extend([limit, offset])
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [serialize(row) for row in cur.fetchall()]


def count_orders(conn, customer_id, status):
    sql = "SELECT COUNT(*) AS n FROM orders WHERE customer_id = %s"
    params = [customer_id]
    if status:
        sql += " AND status = %s"
        params.append(status)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()["n"]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/customers/{customer_id}/orders")
def customer_orders(
    customer_id: int,
    status: Optional[str] = Query(default=None, max_length=20),
    sort: str = Query(default="placed_on", max_length=40),
    direction: str = Query(default="desc", max_length=4),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=PAGE_SIZE_MAX),
    _key: str = Depends(require_key),
    conn=Depends(get_conn),
):
    offset = (page - 1) * per_page
    rows = list_orders(conn, customer_id, status, sort, direction, per_page, offset)
    total = count_orders(conn, customer_id, status)
    log.info("Listed %d order(s) for customer %d", len(rows), customer_id)
    return {"customer_id": customer_id, "page": page, "per_page": per_page, "total": total, "orders": rows}


@app.get("/orders/{order_number}")
def order_detail(order_number: str, _key: str = Depends(require_key), conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, order_number, customer_id, status, placed_on, total FROM orders WHERE order_number = %s",
            (order_number,),
        )
        order = cur.fetchone()
        if order is None:
            raise HTTPException(status_code=404, detail="order not found")
        cur.execute(
            "SELECT sku, description, quantity, unit_price FROM order_items WHERE order_id = %s ORDER BY id",
            (order["id"],),
        )
        items = [serialize(row) for row in cur.fetchall()]
    return {**serialize(order), "items": items}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))