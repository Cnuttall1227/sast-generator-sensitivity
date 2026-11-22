import os
import sys
import uuid
import pickle
import sqlite3
import logging
import asyncio
import tornado.ioloop
import tornado.web
import tornado.websocket
from datetime import datetime

# Configure logging for the Real-Time Game Sync Server
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - GameServer - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TornadoGameSync")

DB_FILE = "mmo_player_stats.db"

def init_game_db():
    """Initializes the SQLite database for storing player statistics."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE player_stats (
            player_id TEXT PRIMARY KEY,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            x_coord REAL NOT NULL,
            y_coord REAL NOT NULL,
            zone_id TEXT NOT NULL,
            health INTEGER NOT NULL
        )
    ''')

    mock_players = [
        ('player_77a91', datetime.now().isoformat(), 105.4, 22.1, 'zone_start', 100),
        ('player_99b22', datetime.now().isoformat(), -44.0, 89.9, 'zone_pvp', 45)
    ]
    cursor.executemany('''
        INSERT INTO player_stats (player_id, last_seen, x_coord, y_coord, zone_id, health)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', mock_players)

    conn.commit()
    conn.close()
    logger.info("Player statistics database initialized.")

def update_player_location(player_id: str, x: float, y: float, zone: str, health: int):
    """Persists the latest player state to the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO player_stats (player_id, last_seen, x_coord, y_coord, zone_id, health)
            VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
            last_seen=CURRENT_TIMESTAMP,
            x_coord=excluded.x_coord,
            y_coord=excluded.y_coord,
            zone_id=excluded.zone_id,
            health=excluded.health
        ''', (player_id, x, y, zone, health))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error updating player {player_id}: {e}")

class PlayerMovementSync:
    """Represents a player's movement and state payload sent over WebSockets."""
    def __init__(self, player_id: str, x: float, y: float, zone: str, health: int):
        self.player_id = player_id
        self.x = x
        self.y = y
        self.zone = zone
        self.health = health

def deserialize_movement_payload(binary_payload: bytes, session_id: str) -> PlayerMovementSync:
    """
    SECURE: Uses JSON instead of pickle to prevent Unsafe Deserialization (CWE-502).
    """
    import json

    logger.debug(f"[{session_id}] Decoding secure binary movement payload.")

    try:
        # Secure: We replace the unsafe pickle module with standard json.
        # json.loads() only parses primitive data structures (dicts, lists, strings, numbers)
        # and strictly prevents arbitrary object instantiation or remote code execution.
        # Note: Game clients connecting to this WebSocket must be updated to send 
        # JSON string payloads encoded as UTF-8 bytes instead of pickled objects.
        
        payload_str = binary_payload.decode('utf-8')
        movement_dict = json.loads(payload_str)

        # Safely and manually reconstruct the PlayerMovementSync object from the parsed dictionary
        if isinstance(movement_dict, dict) and all(k in movement_dict for k in ("player_id", "x", "y", "zone", "health")):
            movement_obj = PlayerMovementSync(
                player_id=str(movement_dict["player_id"]),
                x=float(movement_dict["x"]),
                y=float(movement_dict["y"]),
                zone=str(movement_dict["zone"]),
                health=int(movement_dict["health"])
            )
            return movement_obj
        else:
            logger.warning(f"[{session_id}] Decoded JSON is missing required PlayerMovementSync attributes.")
            return None

    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"[{session_id}] Failed to parse WebSocket frame as JSON: {e}")
        return None
    except ValueError as e:
        logger.error(f"[{session_id}] Invalid data types in movement payload: {e}")
        return None
    except Exception as e:
        logger.error(f"[{session_id}] Unexpected error during deserialization: {e}")
        return None

class GameSyncWebSocket(tornado.websocket.WebSocketHandler):
    """Handles real-time bi-directional communication with game clients."""
    
    def check_origin(self, origin):
        # Insecure CORS policy for demonstration
        return True

    def open(self):
        self.session_id = f"ws_{uuid.uuid4().hex[:8]}"
        logger.info(f"[{self.session_id}] New WebSocket connection established.")

    def on_message(self, message):
        """Processes incoming WebSocket messages (expects binary frames)."""
        if isinstance(message, str):
            logger.warning(f"[{self.session_id}] Expected binary frame, received text. Dropping.")
            self.write_message('{"error": "Text frames are not supported. Use binary."}')
            return

        # message is guaranteed to be bytes here
        logger.debug(f"[{self.session_id}] Received binary frame ({len(message)} bytes)")
        
        # Pass the untrusted binary frame directly to the vulnerable function
        movement = deserialize_movement_payload(message, self.session_id)

        if movement:
            update_player_location(
                movement.player_id,
                movement.x,
                movement.y,
                movement.zone,
                movement.health
            )
            # Acknowledge receipt
            self.write_message(f'{{"status": "ACK", "player": "{movement.player_id}"}}')
        else:
            self.write_message('{"error": "Invalid or corrupted binary payload"}')

    def on_close(self):
        logger.info(f"[{self.session_id}] WebSocket connection closed.")

class HealthCheckHandler(tornado.web.RequestHandler):
    def get(self):
        self.write({"status": "Tornado Game Sync Server is running"})

def make_app():
    return tornado.web.Application([
        (r"/health", HealthCheckHandler),
        (r"/ws/sync", GameSyncWebSocket),
    ], debug=False)

if __name__ == "__main__":
    init_game_db()
    
    port = 8888
    app = make_app()
    app.listen(port)
    logger.info(f"Starting Tornado WebSocket server on ws://0.0.0.0:{port}/ws/sync")
    
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        logger.info("Shutting down Game Sync Server...")
        tornado.ioloop.IOLoop.current().stop()
