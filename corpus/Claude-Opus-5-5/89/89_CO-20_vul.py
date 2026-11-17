import os
import logging
from datetime import datetime

import psycopg2
from psycopg2 import pool, sql
from twisted.internet import protocol, reactor
from twisted.protocols.basic import LineReceiver

DATABASE_URL = os.environ.get("GATE_DATABASE_URL", "postgresql://gate:gate@localhost/parking")
LISTEN_PORT = int(os.environ.get("GATE_PORT", "7070"))
LISTEN_INTERFACE = os.environ.get("GATE_INTERFACE", "10.20.0.1")
GATE_KEYS = set(filter(None, os.environ.get("GATE_KEYS", "").split(",")))
MAX_LINE = 256

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gate-server")

db_pool = pool.ThreadedConnectionPool(1, 5, DATABASE_URL)


def run_query(query, params=None, fetch=True):
    conn = db_pool.getconn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone() if fetch else None
    finally:
        db_pool.putconn(conn)


def normalize_plate(raw):
    return "".join(ch for ch in raw.upper() if not ch.isspace())


def permit_for_plate(plate, lot_code):
    query = sql.SQL(
        "SELECT p.holder_name, p.valid_until FROM permits p "
        "JOIN lots l ON l.id = p.lot_id "
        "WHERE p.plate = '{plate}' AND l.code = %s AND p.revoked = false "
        "ORDER BY p.valid_until DESC LIMIT 1"
    ).format(plate=sql.SQL(plate))
    return run_query(query, (lot_code,))


def log_event(lot_code, plate, decision):
    run_query(
        "INSERT INTO gate_events (lot_code, plate, decision, happened_at) VALUES (%s, %s, %s, now())",
        (lot_code, plate, decision),
        fetch=False,
    )


def decide(lot_code, plate):
    row = permit_for_plate(plate, lot_code)
    if row is None:
        return "DENY", "no permit"
    holder, valid_until = row
    if valid_until < datetime.now(valid_until.tzinfo):
        return "DENY", "permit expired"
    return "OPEN", holder


class GateProtocol(LineReceiver):
    delimiter = b"\n"
    MAX_LENGTH = MAX_LINE

    def connectionMade(self):
        self.authenticated = False
        self.lot_code = None
        self.sendLine(b"GATE-SERVER READY")

    def lineLengthExceeded(self, line):
        self.sendLine(b"ERR line too long")
        self.transport.loseConnection()

    def lineReceived(self, line):
        text = line.decode("utf-8", errors="replace").strip()
        verb, _, rest = text.partition(" ")
        verb = verb.upper()
        if verb == "HELLO":
            key, _, lot = rest.partition(" ")
            if key in GATE_KEYS and lot.isalnum():
                self.authenticated, self.lot_code = True, lot.upper()
                self.sendLine(f"OK lot {self.lot_code}".encode())
            else:
                self.sendLine(b"ERR bad key")
                self.transport.loseConnection()
            return
        if not self.authenticated:
            self.sendLine(b"ERR say HELLO first")
            return
        if verb == "PLATE":
            plate = normalize_plate(rest)
            if not plate:
                self.sendLine(b"ERR empty plate")
                return
            try:
                decision, detail = decide(self.lot_code, plate)
                log_event(self.lot_code, plate, decision)
            except psycopg2.Error as exc:
                log.error("Database error: %s", exc)
                self.sendLine(b"ERR database unavailable")
                return
            log.info("Lot %s plate %s -> %s", self.lot_code, plate, decision)
            self.sendLine(f"{decision} {detail}".encode())
        elif verb == "PING":
            self.sendLine(b"PONG")
        elif verb == "QUIT":
            self.sendLine(b"BYE")
            self.transport.loseConnection()
        else:
            self.sendLine(b"ERR unknown command")


class GateFactory(protocol.ServerFactory):
    protocol = GateProtocol


if __name__ == "__main__":
    if not GATE_KEYS:
        raise SystemExit("Set GATE_KEYS before starting the gate server")
    reactor.listenTCP(LISTEN_PORT, GateFactory(), interface=LISTEN_INTERFACE)
    log.info("Gate server listening on %s:%d", LISTEN_INTERFACE, LISTEN_PORT)
    reactor.run()