import sqlite3
import os
import logging
from flask import Flask, request, jsonify, make_response, redirect, url_for

# Configure logging for the Flask Web Application
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - EmployeePortal - %(levelname)s - %(message)s'
)
logger = logging.getLogger("InternalFlaskPortal")

DB_FILE = "corporate_intranet.db"
app = Flask(__name__)

def initialize_portal_database():
    """Initializes the SQLite database with session tokens and sensitive HR data."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Create session tracking table (Target for primary queries)
    cursor.execute('''
        CREATE TABLE employee_sessions (
            session_token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            theme_preference TEXT DEFAULT 'light'
        )
    ''')

    # Create highly sensitive HR data table (Target for exfiltration via SQLi)
    cursor.execute('''
        CREATE TABLE hr_salary_data (
            emp_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            annual_salary INTEGER NOT NULL,
            social_security_number TEXT NOT NULL
        )
    ''')

    # Populate mock active sessions
    mock_sessions = [
        ('token_abc123_admin', 'admin_sarah', 'Administrator', 'dark'),
        ('token_def456_user', 'jdoe', 'Employee', 'light'),
        ('token_ghi789_user', 'mscott', 'Manager', 'dark')
    ]
    cursor.executemany('''
        INSERT INTO employee_sessions (session_token, username, role, theme_preference)
        VALUES (?, ?, ?, ?)
    ''', mock_sessions)

    # Populate sensitive HR records
    mock_hr_data = [
        ('admin_sarah', 150000, 'AAA-GG-SSSS'),
        ('jdoe', 75000, 'BBB-GG-SSSS'),
        ('mscott', 110000, 'CCC-GG-SSSS'),
        ('ceo_david', 500000, 'DDD-GG-SSSS')
    ]
    cursor.executemany('''
        INSERT INTO hr_salary_data (username, annual_salary, social_security_number)
        VALUES (?, ?, ?)
    ''', mock_hr_data)

    conn.commit()
    conn.close()
    logger.info("Corporate Intranet database initialized.")


def fetch_session_details(session_token: str):
    """
    VULNERABLE FUNCTION: CWE-89 SQL Injection
    Trigger Path: HTTP Cookie parsing (extracting session token from request.cookies)
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Vulnerability: Direct string concatenation of the HTTP Cookie value into the SQL query
    query = f"SELECT username, role, theme_preference FROM employee_sessions WHERE session_token = '{session_token}'"

    try:
        logger.info(f"Validating session via query: {query}")
        cursor.execute(query)
        record = cursor.fetchone()

        if record:
            return {
                "valid": True, 
                "username": record[0], 
                "role": record[1], 
                "theme": record[2]
            }
        return {"valid": False, "error": "Invalid session token"}

    except sqlite3.Error as e:
        logger.error(f"Database error during session validation: {e}")
        # Returning the database error directly allows error-based SQL injection via HTTP responses
        return {"valid": False, "error": f"Database execution failed: {e}"}
    finally:
        conn.close()


@app.route('/')
def index():
    """Root route that redirects to the dashboard."""
    return redirect(url_for('dashboard'))


@app.route('/login', methods=['GET'])
def mock_login():
    """Mock login endpoint that sets a valid cookie for testing."""
    resp = make_response(jsonify({"status": "success", "message": "Logged in successfully as jdoe."}))
    resp.set_cookie('auth_session', 'token_def456_user')
    return resp


@app.route('/dashboard', methods=['GET'])
def dashboard():
    """
    Protected dashboard endpoint.
    Retrieves the 'auth_session' cookie directly from the HTTP request headers.
    """
    # Extracting the HTTP cookie value
    session_cookie = request.cookies.get('auth_session')

    if not session_cookie:
        return jsonify({"status": "unauthorized", "message": "Missing auth_session cookie."}), 401

    # Triggering the vulnerable function with the untrusted cookie data
    session_info = fetch_session_details(session_cookie)

    if not session_info.get("valid"):
        return jsonify({
            "status": "forbidden", 
            "message": "Access denied.", 
            "details": session_info.get("error")
        }), 403

    return jsonify({
        "status": "success",
        "message": f"Welcome to the intranet, {session_info['username']}!",
        "dashboard_data": {
            "user_role": session_info['role'],
            "ui_theme": session_info['theme'],
            "company_announcements": [
                "Q3 All-Hands meeting on Friday.",
                "Update your benefits enrollment by the 15th."
            ]
        }
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Basic API health check."""
    return jsonify({"status": "healthy", "service": "Intranet Portal"})


if __name__ == '__main__':
    # Initialize the database on startup
    initialize_portal_database()
    
    # Example Malicious cURL Request exploiting the HTTP Cookie:
    # curl -X GET http://127.0.0.1:5000/dashboard -H "Cookie: auth_session=token_def456_user' UNION SELECT username, social_security_number, annual_salary FROM hr_salary_data--"
    
    logger.info("Starting Flask Intranet Portal on http://127.0.0.1:5000")
    app.run(host='127.0.0.1', port=5000, debug=False)
