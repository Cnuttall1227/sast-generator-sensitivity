import asyncio
import sqlite3
import os
import logging
import json
from aiohttp import web
from datetime import datetime

# Configure logging for the Async Network Diagnostics API
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - NetDiagAPI - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AsyncNetDiagnostics")

DB_FILE = "diagnostics_audit.db"
API_HOST = "127.0.0.1"
API_PORT = 8080

def initialize_audit_db():
    """Initializes the local SQLite database for auditing network diagnostic runs."""
    is_new = not os.path.exists(DB_FILE)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            api_token TEXT NOT NULL,
            target_host TEXT NOT NULL,
            diagnostic_type TEXT NOT NULL,
            execution_status TEXT NOT NULL
        )
    ''')

    if is_new:
        logger.info("Created new diagnostic audit database.")
    
    conn.commit()
    conn.close()

def log_diagnostic_run(api_token: str, target: str, diag_type: str, status: str):
    """Synchronous function to log diagnostic executions to the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO audit_logs (api_token, target_host, diagnostic_type, execution_status)
            VALUES (?, ?, ?, ?)
        ''', (api_token, target, diag_type, status))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to write audit log: {e}")

async def execute_ping_diagnostic(target_host: str, count: int):
    """
    SECURE: Uses create_subprocess_exec without a shell to prevent Command Injection.
    """
    try:
        logger.info(f"Executing secure system diagnostic command for target: {target_host}")
        
        # asyncio.create_subprocess_exec avoids the system shell entirely.
        # Arguments are passed as a list, neutralizing shell metacharacters (;, &&, |).
        process = await asyncio.create_subprocess_exec(
            "ping", "-c", str(count), target_host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            return {"success": True, "output": stdout.decode('utf-8')}
        else:
            # Masking raw stderr in failure cases to prevent leaking system information
            return {"success": False, "error": "Ping command failed or host unreachable."}
            
    except Exception as e:
        logger.error(f"Command execution exception: {e}")
        return {"success": False, "error": "Internal diagnostic execution error."}

@web.middleware
async def authentication_middleware(request, handler):
    """Basic middleware to enforce API token authorization."""
    auth_header = request.headers.get("Authorization")
    
    if not auth_header or not auth_header.startswith("Bearer "):
        return web.json_response({"error": "Missing or invalid Authorization header"}, status=401)
        
    token = auth_header.split(" ")[1]
    
    # Hardcoded mock token for dataset demonstration purposes
    if token != "dev_admin_token_99":
        return web.json_response({"error": "Unauthorized API Token"}, status=403)
        
    request['api_token'] = token
    return await handler(request)

async def handle_ping_request(request):
    """Aiohttp route handler for processing network ping requests."""
    try:
        # Extract untrusted JSON payload from the HTTP POST body
        payload = await request.json()
        
        target_host = payload.get("target_host")
        count = payload.get("count", 4)  # Default to 4 pings
        
        if not target_host:
            return web.json_response({"error": "Missing required field: target_host"}, status=400)
            
        # Ensure count is an integer to prevent injection in the 'count' field
        try:
            count = int(count)
        except ValueError:
            return web.json_response({"error": "Field 'count' must be an integer"}, status=400)

        # Triggering the vulnerable command execution function
        result = await execute_ping_diagnostic(target_host, count)
        
        # Log the action (Audit trailing)
        status_flag = "SUCCESS" if result["success"] else "FAILED"
        log_diagnostic_run(request['api_token'], target_host, "PING", status_flag)
        
        return web.json_response(result)

    except json.JSONDecodeError:
        return web.json_response({"error": "Malformed JSON payload"}, status=400)

def create_app():
    """Configures the aiohttp web application and routes."""
    initialize_audit_db()
    
    app = web.Application(middlewares=[authentication_middleware])
    app.router.add_post('/api/v1/diagnostics/ping', handle_ping_request)
    
    return app

if __name__ == "__main__":
    # Example Malicious cURL Request exploiting the JSON POST body:
    # curl -X POST http://127.0.0.1:8080/api/v1/diagnostics/ping \
    #      -H "Authorization: Bearer dev_admin_token_99" \
    #      -H "Content-Type: application/json" \
    #      -d '{"target_host": "8.8.8.8; cat /etc/passwd", "count": 1}'
    
    app = create_app()
    logger.info(f"Starting Async Network Diagnostics API on http://{API_HOST}:{API_PORT}")
    web.run_app(app, host=API_HOST, port=API_PORT, access_log=None)
