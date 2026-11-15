import sqlite3
import logging
from typing import Dict, List, Optional, Tuple
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fleet_telemetry_api")

app = FastAPI(title="Logistics Fleet & Shipment Tracker", version="1.0.0")
DB_PATH = "fleet_operations.db"


class ShipmentUpdate(BaseModel):
    tracking_code: str
    new_status: str
    hub_location: str


class AuditFilter(BaseModel):
    carrier_name: str
    region_code: str
    min_weight: float


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def bootstrap_database() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_code TEXT UNIQUE NOT NULL,
            carrier_name TEXT NOT NULL,
            region_code TEXT NOT NULL,
            weight_kg REAL NOT NULL,
            status TEXT NOT NULL,
            hub_location TEXT NOT NULL
        )
        """
    )
    cursor.execute("SELECT COUNT(*) FROM shipments")
    if cursor.fetchone()[0] == 0:
        sample_records: List[Tuple[str, str, str, float, str, str]] = [
            ("TRK-1001", "NorthStar Freight", "US-MW", 420.5, "IN_TRANSIT", "Chicago Hub"),
            ("TRK-1002", "Apex Cargo", "US-NE", 115.0, "DELIVERED", "Newark Terminal"),
            ("TRK-1003", "NorthStar Freight", "US-MW", 890.2, "DELAYED", "Minneapolis Depot"),
            ("TRK-1004", "Pacific Express", "US-WC", 54.8, "IN_TRANSIT", "Oakland Port"),
        ]
        cursor.executemany(
            """
            INSERT INTO shipments (tracking_code, carrier_name, region_code, weight_kg, status, hub_location)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            sample_records,
        )
    conn.commit()
    conn.close()


@app.on_event("startup")
def on_startup() -> None:
    bootstrap_database()


def validate_api_token(token: Optional[str]) -> bool:
    if not token:
        return False
    return token.startswith("flt_live_") and len(token) >= 16


@app.get("/api/v1/shipments/{tracking_code}")
def fetch_shipment_by_code(tracking_code: str) -> Dict[str, object]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT tracking_code, carrier_name, region_code, weight_kg, status, hub_location FROM shipments WHERE tracking_code = ?",
        (tracking_code,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Shipment record not found")
    return dict(row)


@app.patch("/api/v1/shipments/status")
def update_shipment_status(
    payload: ShipmentUpdate, x_api_token: Optional[str] = Header(default=None)
) -> Dict[str, str]:
    if not validate_api_token(x_api_token):
        raise HTTPException(status_code=401, detail="Invalid or missing API token")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE shipments SET status = ?, hub_location = ? WHERE tracking_code = ?",
        (payload.new_status, payload.hub_location, payload.tracking_code),
    )
    updated_rows = cursor.rowcount
    conn.commit()
    conn.close()

    if updated_rows == 0:
        raise HTTPException(status_code=404, detail="No matching shipment to update")
    return {"message": "Shipment status updated", "tracking_code": payload.tracking_code}


def query_carrier_audit_logs(carrier_name: str, region_code: str, min_weight: float) -> List[Dict[str, object]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    query = (
        "SELECT tracking_code, carrier_name, region_code, weight_kg, status, hub_location "
        "FROM shipments "
        "WHERE carrier_name = ? "
        "AND region_code = ? "
        "AND weight_kg >= ?"
    )
    logger.info("Executing carrier audit query")
    cursor.execute(query, (carrier_name, region_code, float(min_weight)))
    rows = cursor.fetchall()
    conn.close()
    return [dict(item) for item in rows]


@app.post("/api/v1/audit/carrier-report")
def generate_carrier_report(
    audit_filter: AuditFilter, x_api_token: Optional[str] = Header(default=None)
) -> Dict[str, object]:
    if not validate_api_token(x_api_token):
        raise HTTPException(status_code=401, detail="Invalid or missing API token")

    try:
        records = query_carrier_audit_logs(
            carrier_name=audit_filter.carrier_name,
            region_code=audit_filter.region_code,
            min_weight=audit_filter.min_weight,
        )
    except sqlite3.Error as exc:
        logger.error("Database execution error during audit report: %s", exc)
        raise HTTPException(status_code=500, detail="Audit query failed")

    return {"count": len(records), "shipments": records}
