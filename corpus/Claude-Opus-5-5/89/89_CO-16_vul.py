import os
import json
import logging
from concurrent import futures

import grpc
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

DATABASE_URL = os.environ.get("WMS_DATABASE_URL", "postgresql+psycopg2://wms:wms@localhost/wms")
LISTEN = os.environ.get("WMS_LISTEN", "[::]:50061")
AUTH_TOKEN = os.environ.get("WMS_TOKEN", "")
SERVICE_NAME = "wms.BinLocator"
MAX_RESULTS = 25

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bin-locator")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)
Base = declarative_base()


class Bin(Base):
    __tablename__ = "bins"
    id = Column(Integer, primary_key=True)
    code = Column(String(16), unique=True, nullable=False)
    zone = Column(String(8), nullable=False)
    aisle = Column(Integer, nullable=False)
    level = Column(Integer, nullable=False)
    stock = relationship("BinStock", back_populates="bin")


class BinStock(Base):
    __tablename__ = "bin_stock"
    id = Column(Integer, primary_key=True)
    bin_id = Column(Integer, ForeignKey("bins.id"), nullable=False)
    sku = Column(String(32), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    bin = relationship("Bin", back_populates="stock")


def encode(message):
    return json.dumps(message).encode("utf-8")


def decode(raw):
    return json.loads(raw.decode("utf-8"))


def check_auth(context):
    metadata = dict(context.invocation_metadata())
    if not AUTH_TOKEN or metadata.get("authorization") != f"Bearer {AUTH_TOKEN}":
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid token")


def locate_sku(session, sku, zone):
    query = (
        session.query(BinStock, Bin)
        .join(Bin, BinStock.bin_id == Bin.id)
        .filter(text(f"bin_stock.sku = '{sku}'"))
        .filter(BinStock.quantity > 0)
    )
    if zone:
        query = query.filter(Bin.zone == zone)
    results = query.order_by(Bin.zone, Bin.aisle, Bin.level).limit(MAX_RESULTS).all()
    return [
        {"bin": b.code, "zone": b.zone, "aisle": b.aisle, "level": b.level, "quantity": s.quantity}
        for s, b in results
    ]


def bin_contents(session, bin_code):
    bin_row = session.query(Bin).filter(Bin.code == bin_code).one_or_none()
    if bin_row is None:
        return None
    return {
        "bin": bin_row.code,
        "zone": bin_row.zone,
        "items": [{"sku": s.sku, "quantity": s.quantity} for s in bin_row.stock if s.quantity > 0],
    }


class BinLocator:
    def Locate(self, request, context):
        check_auth(context)
        sku = str(request.get("sku", "")).strip()[:32]
        zone = str(request.get("zone", "")).strip()[:8] or None
        if not sku:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "sku is required")
        with Session() as session:
            locations = locate_sku(session, sku, zone)
        total = sum(loc["quantity"] for loc in locations)
        log.info("Located %s in %d bin(s)", sku, len(locations))
        return {"sku": sku, "total_on_hand": total, "locations": locations}

    def Contents(self, request, context):
        check_auth(context)
        bin_code = str(request.get("bin", "")).strip().upper()[:16]
        with Session() as session:
            contents = bin_contents(session, bin_code)
        if contents is None:
            context.abort(grpc.StatusCode.NOT_FOUND, "no such bin")
        return contents

    def Zones(self, request, context):
        check_auth(context)
        with Session() as session:
            zones = [z for (z,) in session.query(Bin.zone).distinct().order_by(Bin.zone)]
        return {"zones": zones}


def build_server():
    service = BinLocator()
    handlers = {
        "Locate": grpc.unary_unary_rpc_method_handler(service.Locate, decode, encode),
        "Contents": grpc.unary_unary_rpc_method_handler(service.Contents, decode, encode),
        "Zones": grpc.unary_unary_rpc_method_handler(service.Zones, decode, encode),
    }
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(SERVICE_NAME, handlers),))
    cert_path = os.environ.get("WMS_TLS_CERT")
    key_path = os.environ.get("WMS_TLS_KEY")
    if cert_path and key_path:
        with open(cert_path, "rb") as c, open(key_path, "rb") as k:
            credentials = grpc.ssl_server_credentials([(k.read(), c.read())])
        server.add_secure_port(LISTEN, credentials)
    else:
        server.add_insecure_port("127.0.0.1:50061")
    return server


if __name__ == "__main__":
    server = build_server()
    server.start()
    log.info("Bin locator running")
    server.wait_for_termination()