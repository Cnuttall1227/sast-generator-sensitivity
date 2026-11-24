import os
import sys
import uuid
import sqlite3
import logging
import jsonpickle
from datetime import datetime
from aiohttp import web

# Configure logging for the IoT Device Shadow Synchronization Service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - ShadowSync - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AiohttpShadowService")

DB_FILE = "device_shadows.db"

def init_shadow_db():
    """Initializes the SQLite database for storing IoT device shadow states."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE device_shadows (
            device_id TEXT PRIMARY KEY,
            last_synced DATETIME DEFAULT CURRENT_TIMESTAMP,
            firmware_version TEXT NOT NULL,
            battery_level INTEGER,
            reported_state TEXT NOT NULL
        )
    ''')

    mock_devices = [
        ('thermostat_01', datetime.now().isoformat(), 'v2.4.1', 98, '{"target_temp": 71, "mode": "auto"}'),
        ('lock_front_door', datetime.now().isoformat(), 'v1.9.0', 64, '{"locked": true, "auto_relock": 30}')
    ]
    cursor.executemany('''
        INSERT INTO device_shadows (device_id, last_synced, firmware_version, battery_level, reported_state)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_devices)

    conn.commit()
    conn.close()
    logger.info("Device shadow database initialized.")

def upsert_device_shadow(device_id: str, firmware: str, battery: int, state_summary: str):
    """Updates or inserts the latest reported state of an IoT device."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO device_shadows (device_id, last_synced, firmware_version, battery_level, reported_state)
            VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
            last_synced=CURRENT_TIMESTAMP,
            firmware_version=excluded.firmware_version,
            battery_level=excluded.battery_level,
            reported_state=excluded.reported_state
        ''', (device_id, firmware, battery, state_summary))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error updating shadow for {device_id}: {e}")

class DeviceShadowPayload:
    """Represents a complex nested state object reported by an IoT gateway."""
    def __init__(self, device_id: str, firmware: str, battery: int, telemetry: dict):
        self.device_id = device_id
        self.firmware = firmware
        self.battery = battery
        self.telemetry = telemetry

def decode_device_shadow(raw_json_str: str, sync_id: str) -> DeviceShadowPayload:
    """
    SECURE: Uses standard json.loads instead of jsonpickle to prevent Unsafe Deserialization (CWE-502).
    """
    import json

    logger.info(f"[{sync_id}] Decoding secure IoT device shadow payload.")

    try:
        # Secure: Replace jsonpickle.decode() with standard json.loads().
        # Standard JSON only parses primitive types (dicts, lists, strings, numbers, booleans)
        # and ignores or rejects arbitrary object instantiation metadata like 'py/object' or 'py/reduce'.
        shadow_dict = json.loads(raw_json_str)

        required_keys = ("device_id", "firmware", "battery", "telemetry")
        if isinstance(shadow_dict, dict) and all(k in shadow_dict for k in required_keys):
            if not isinstance(shadow_dict["telemetry"], dict):
                logger.warning(f"[{sync_id}] 'telemetry' field must be a JSON object.")
                return None

            shadow_obj = DeviceShadowPayload(
                device_id=str(shadow_dict["device_id"]),
                firmware=str(shadow_dict["firmware"]),
                battery=int(shadow_dict["battery"]),
                telemetry=shadow_dict["telemetry"]
            )
            logger.debug(f"[{sync_id}] Safely decoded shadow for device: {shadow_obj.device_id}")
            return shadow_obj
        else:
            logger.warning(f"[{sync_id}] Decoded JSON is missing required DeviceShadowPayload fields.")
            return None

    except json.JSONDecodeError as e:
        logger.error(f"[{sync_id}] Failed to parse payload as valid JSON: {e}")
        return None
    except (ValueError, TypeError) as e:
        logger.error(f"[{sync_id}] Invalid data types in shadow payload: {e}")
        return None
    except Exception as e:
        logger.error(f"[{sync_id}] Unexpected error decoding device shadow: {e}")
        return None

async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint for the async IoT gateway."""
    return web.json_response({"status": "IoT Shadow Sync Service is healthy"})

async def handle_shadow_sync(request: web.Request) -> web.Response:
    """Async endpoint accepting device state updates via HTTP PUT."""
    sync_id = f"sync_{uuid.uuid4().hex[:8]}"
    device_id_param = request.match_info.get('device_id', 'unknown')

    try:
        raw_body = await request.text()
        if not raw_body:
            return web.json_response({"error": "Empty request body"}, status=400)

        logger.info(f"[{sync_id}] Received shadow update for '{device_id_param}' ({len(raw_body)} chars)")

        shadow = decode_device_shadow(raw_body, sync_id)

        if shadow and shadow.device_id == device_id_param:
            upsert_device_shadow(
                shadow.device_id,
                shadow.firmware,
                shadow.battery,
                str(shadow.telemetry)
            )
            return web.json_response({
                "status": "SYNCHRONIZED",
                "sync_id": sync_id,
                "device_id": shadow.device_id
            }, status=200)
        else:
            return web.json_response({
                "error": "Invalid shadow payload or device_id mismatch"
            }, status=422)

    except UnicodeDecodeError:
        logger.error(f"[{sync_id}] Invalid UTF-8 payload received.")
        return web.json_response({"error": "Invalid encoding"}, status=400)
    except Exception as e:
        logger.error(f"[{sync_id}] Error handling shadow sync: {e}")
        return web.json_response({"error": "Internal server error"}, status=500)

def create_app() -> web.Application:
    """Configures routes and returns the aiohttp web application."""
    app = web.Application()
    app.router.add_get('/health', handle_health)
    app.router.add_put('/api/v1/devices/{device_id}/shadow', handle_shadow_sync)
    return app

if __name__ == '__main__':
    init_shadow_db()
    application = create_app()
    logger.info("Starting aiohttp IoT Shadow Sync Service on port 8080")
    web.run_app(application, host='0.0.0.0', port=8080, print=None)
