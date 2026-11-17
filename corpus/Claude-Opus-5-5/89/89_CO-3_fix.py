import os
import logging
from decimal import Decimal

from flask import Flask, abort, jsonify, request
from sqlalchemy import create_engine, text
from sqlalchemy import bindparam

DATABASE_URL = os.environ.get("CATALOG_DATABASE_URL", "mysql+pymysql://catalog:catalog@localhost/catalog")
MAX_IDS_PER_REQUEST = 50

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("catalog-api")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
app = Flask(__name__)


def to_json(row):
    data = dict(row._mapping)
    for key, value in data.items():
        if isinstance(value, Decimal):
            data[key] = str(value)
    return data


def parse_id_list(raw):
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    if not ids:
        abort(400, description="ids must list at least one product id")
    if len(ids) > MAX_IDS_PER_REQUEST:
        abort(400, description=f"at most {MAX_IDS_PER_REQUEST} ids per request")
    return ids


def fetch_products_by_ids(ids):
    try:
        id_values = sorted({int(i) for i in ids})
    except ValueError:
        abort(400, description="ids must be whole numbers separated by commas")
    if not id_values:
        return []
    query = text(
        "SELECT p.id, p.sku, p.name, p.price, p.currency, COALESCE(s.on_hand, 0) AS on_hand "
        "FROM products p LEFT JOIN stock s ON s.product_id = p.id "
        "WHERE p.active = 1 AND p.id IN :ids "
        "ORDER BY p.name"
    ).bindparams(bindparam("ids", expanding=True))
    with engine.connect() as conn:
        return [to_json(row) for row in conn.execute(query, {"ids": id_values})]


def fetch_product(product_id):
    query = text(
        "SELECT p.id, p.sku, p.name, p.description, p.price, p.currency, COALESCE(s.on_hand, 0) AS on_hand "
        "FROM products p LEFT JOIN stock s ON s.product_id = p.id WHERE p.id = :id AND p.active = 1"
    )
    with engine.connect() as conn:
        row = conn.execute(query, {"id": product_id}).first()
    return to_json(row) if row else None


def fetch_categories():
    query = text(
        "SELECT c.slug, c.name, COUNT(p.id) AS products FROM categories c "
        "LEFT JOIN products p ON p.category_id = c.id AND p.active = 1 "
        "GROUP BY c.id ORDER BY c.name"
    )
    with engine.connect() as conn:
        return [to_json(row) for row in conn.execute(query)]


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return jsonify(status="ok")


@app.get("/products")
def products_bulk():
    raw_ids = request.args.get("ids", "")
    ids = parse_id_list(raw_ids)
    products = fetch_products_by_ids(ids)
    found = {str(p["id"]) for p in products}
    missing = [i for i in ids if i not in found]
    log.info("Bulk lookup of %d id(s), %d found", len(ids), len(products))
    return jsonify(products=products, missing=missing)


@app.get("/products/<int:product_id>")
def product_detail(product_id):
    product = fetch_product(product_id)
    if product is None:
        abort(404, description="product not found")
    return jsonify(product)


@app.get("/categories")
def categories():
    return jsonify(categories=fetch_categories())


@app.errorhandler(400)
@app.errorhandler(404)
def json_error(error):
    return jsonify(error=getattr(error, "description", str(error))), error.code


@app.errorhandler(500)
def server_error(error):
    log.exception("Unhandled error")
    return jsonify(error="internal server error"), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))