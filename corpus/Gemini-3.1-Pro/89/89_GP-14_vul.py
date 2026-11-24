import json
import sqlite3
import os
import logging
from paho.mqtt import client as mqtt_client

# Configure logging for the IoT Telemetry Service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - IoT_Gateway - %(levelname)s - %(message)s'
)
logger = logging.getLogger("IoT_Telemetry_Gateway")

DB_FILE = "iot_fleet_management.db"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "factory/telemetry/#"

def initialize_iot_database():
    """Initializes the SQLite database with sensor registry and telemetry logs."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Create sensor registry table
    cursor.execute('''
        CREATE TABLE sensor_registry (
            sensor_id TEXT PRIMARY KEY,
            location TEXT NOT NULL,
            maintenance_status TEXT NOT NULL,
            firmware_version TEXT NOT NULL
        )
    ''')

    # Create telemetry time-series table
    cursor.execute('''
        CREATE TABLE telemetry_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sensor_id TEXT,
            temperature REAL,
            humidity REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(sensor_id) REFERENCES sensor_registry(sensor_id)
        )
    ''')

    # Insert mock sensor devices
    mock_sensors = [
        ('ZON-A-TEMP-01', 'Assembly Line A', 'ACTIVE', 'v2.4.1'),
        ('ZON-A-HUM-02', 'Assembly Line A', 'MAINTENANCE', 'v2.4.0'),
        ('ZON-B-TEMP-01', 'Warehouse B', 'ACTIVE', 'v1.9.9'),
        ('SYS-ADMIN-NODE', 'Server Room', 'ACTIVE', 'v3.0.0')
    ]
    cursor.executemany('''
        INSERT INTO sensor_registry (sensor_id, location, maintenance_status, firmware_version)
        VALUES (?, ?, ?, ?)
    ''', mock_sensors)

    conn.commit()
    conn.close()
    logger.info("IoT database initialized with sensor registry.")

def check_sensor_status(sensor_id: str):
    """
    VULNERABLE FUNCTION: CWE-89 SQL Injection
    Trigger Path: IoT MQTT Message Payload parsing (extracting sensor_id from JSON telemetry)
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Vulnerability: Direct string concatenation of the JSON parsed field into the SQL query
    query = f"SELECT location, maintenance_status FROM sensor_registry WHERE sensor_id = '{sensor_id}'"

    try:
        logger.debug(f"Verifying sensor status with query: {query}")
        cursor.execute(query)
        record = cursor.fetchone()

        if record:
            return {
                "registered": True,
                "location": record[0],
                "status": record[1]
            }
        return {"registered": False, "status": "UNKNOWN"}

    except sqlite3.Error as e:
        logger.error(f"Database error during sensor verification: {e}")
        # Returning the exact database error can facilitate error-based SQL injection via IoT logs/responses
        return {"registered": False, "error": str(e)}
    finally:
        conn.close()

def record_telemetry(sensor_id, temperature, humidity):
    """Securely logs incoming sensor telemetry using parameterized queries."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO telemetry_data (sensor_id, temperature, humidity)
            VALUES (?, ?, ?)
        ''', (sensor_id, temperature, humidity))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Failed to record telemetry for {sensor_id}: {e}")
    finally:
        conn.close()

def on_connect(client, userdata, flags, rc):
    """Callback for when the client receives a CONNACK response from the server."""
    if rc == 0:
        logger.info("Successfully connected to MQTT Broker.")
        client.subscribe(MQTT_TOPIC)
        logger.info(f"Subscribed to topic: {MQTT_TOPIC}")
    else:
        logger.error(f"Failed to connect to MQTT Broker, return code {rc}")

def on_message(client, userdata, msg):
    """Handles incoming MQTT messages containing IoT telemetry."""
    payload_str = msg.payload.decode('utf-8')
    logger.info(f"Received message on {msg.topic}: {payload_str}")

    try:
        # Parse the incoming JSON payload from the MQTT message
        payload = json.loads(payload_str)
        
        sensor_id = payload.get("sensor_id")
        temp = payload.get("temperature")
        hum = payload.get("humidity")

        if not sensor_id:
            logger.warning("Dropped message: Missing sensor_id")
            return

        # Triggering the vulnerable function using data extracted from the MQTT JSON payload
        sensor_info = check_sensor_status(sensor_id)

        if not sensor_info.get("registered"):
            logger.warning(f"Dropped message: Unregistered or invalid sensor_id: {sensor_id}")
            if "error" in sensor_info:
                logger.error(f"SQL Error trace: {sensor_info['error']}")
            return
            
        if sensor_info.get("status") == "MAINTENANCE":
            logger.warning(f"Ignored telemetry from {sensor_id} (Maintenance Mode)")
            return

        # If registered and active, save the telemetry
        if temp is not None and hum is not None:
            record_telemetry(sensor_id, temp, hum)
            logger.info(f"Recorded telemetry for {sensor_id} ({sensor_info['location']})")
        
    except json.JSONDecodeError:
        logger.error("Dropped message: Invalid JSON payload format")

def start_iot_gateway():
    """Configures and starts the MQTT client to listen for sensor data."""
    initialize_iot_database()
    
    client = mqtt_client.Client("IoT_Gateway_Service")
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        logger.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except ConnectionRefusedError:
        logger.error(f"Connection refused. Ensure an MQTT broker is running on {MQTT_BROKER}:{MQTT_PORT}")
    except KeyboardInterrupt:
        logger.info("Shutting down IoT Gateway.")
        client.disconnect()

if __name__ == "__main__":
    # Example Malicious MQTT Payload to publish to topic 'factory/telemetry/zoneA':
    # {
    #     "sensor_id": "ZON-A-TEMP-01' UNION SELECT location, 'ACTIVE' FROM sensor_registry WHERE sensor_id='SYS-ADMIN-NODE'--",
    #     "temperature": 25.5,
    #     "humidity": 40.0
    # }
    
    start_iot_gateway()
