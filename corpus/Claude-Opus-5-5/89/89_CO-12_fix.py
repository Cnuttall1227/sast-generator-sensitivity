import os
import logging
from decimal import Decimal
from typing import Any

import psycopg
import uvicorn
from litestar import Litestar, Request, get, post
from litestar.exceptions import NotAuthorizedException, ValidationException
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("LISTINGS_DATABASE_URL", "postgresql://listings:listings@localhost/listings")
API_KEYS = set(filter(None, os.environ.get("LISTINGS_API_KEYS", "").split(",")))
FILTERABLE = {
    "price": "l.price",
    "bedrooms": "l.bedrooms",
    "bathrooms": "l.bathrooms",
    "square_feet": "l.square_feet",
    "city": "l.city",
    "listed_on": "l.listed_on",
}
MAX_FILTERS = 8
MAX_RESULTS = 100
ALLOWED_OPERATORS = {
    "=": "=",
    "!=": "<>",
    "<>": "<>",
    "<": "<",
    "<=": "<=",
    ">": ">",
    ">=": ">=",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("listings-search")


def require_key(request: Request) -> None:
    if not API_KEYS or request.headers.get("x-api-key", "") not in API_KEYS:
        raise NotAuthorizedException("API key required")


def jsonable(row: dict) -> dict:
    return {k: (str(v) if isinstance(v, Decimal) else v.isoformat() if hasattr(v, "isoformat") else v)
            for k, v in row.items()}


def build_where(filters: list) -> tuple:
    clauses = ["l.status = 'active'"]
    params: list[Any] = []
    for item in filters:
        if not isinstance(item, dict):
            raise ValidationException("each filter must be an object")
        column = FILTERABLE.get(item.get("field"))
        if column is None:
            raise ValidationException(f"cannot filter on {item.get('field')!r}")
        operator = ALLOWED_OPERATORS.get(str(item.get("op", "=")).strip())
        if operator is None:
            raise ValidationException(
                f"op must be one of: {', '.join(ALLOWED_OPERATORS)}"
            )
        clauses.append(f"{column} {operator} %s")
        params.append(item.get("value"))
    return " AND ".join(clauses), params


def search_listings(filters: list, limit: int) -> list:
    where, params = build_where(filters)
    sql = (
        "SELECT l.id, l.headline, l.street, l.city, l.price, l.bedrooms, l.bathrooms, "
        "l.square_feet, l.listed_on FROM listings l "
        f"WHERE {where} ORDER BY l.listed_on DESC LIMIT %s"
    )
    params.append(limit)
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        return [jsonable(r) for r in conn.execute(sql, params).fetchall()]


@get("/health")
async def health() -> dict:
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@post("/listings/search")
async def search(request: Request, data: dict) -> dict:
    require_key(request)
    filters = data.get("filters", [])
    if not isinstance(filters, list) or len(filters) > MAX_FILTERS:
        raise ValidationException(f"filters must be a list of at most {MAX_FILTERS} items")
    try:
        limit = max(1, min(int(data.get("limit", 25)), MAX_RESULTS))
    except (TypeError, ValueError):
        raise ValidationException("limit must be a number")
    try:
        results = search_listings(filters, limit)
    except psycopg.errors.DataError:
        raise ValidationException("a filter value has the wrong type for its field")
    log.info("Search with %d filter(s) returned %d listing(s)", len(filters), len(results))
    return {"count": len(results), "listings": results, "filterable_fields": list(FILTERABLE)}


@get("/listings/{listing_id:int}")
async def listing(request: Request, listing_id: int) -> dict:
    require_key(request)
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT id, headline, description, street, city, price, bedrooms, bathrooms, "
            "square_feet, listed_on, status FROM listings WHERE id = %s",
            (listing_id,),
        ).fetchone()
    if row is None:
        raise ValidationException("listing not found", status_code=404)
    return jsonable(row)


app = Litestar(route_handlers=[health, search, listing])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))