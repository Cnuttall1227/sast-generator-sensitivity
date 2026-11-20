import asyncio
import websockets
import json
import sqlite3
import os
import logging
from datetime import datetime

# Configure logging for the WebSocket server
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("WebSocketChatServer")

DB_FILE = "chat_archive.db"

def initialize_chat_database():
    """Initializes the chat database with schemas and mock data."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # User accounts and roles table
    cursor.execute('''
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            password_hash TEXT NOT NULL
        )
    ''')
    
    # Chat messages table
    cursor.execute('''
        CREATE TABLE messages (
            msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_name TEXT NOT NULL,
            sender TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Insert mock user data
    cursor.executemany('INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)', [
        ('admin', 'admin', '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918'),
        ('alice', 'member', '910078864d8dbec3f7e59b20755f8cebb5bd19db79fbb2cf95632dd29ee43b23'),
        ('bob', 'member', '2e0a80c98f860fb776cf361ff58085295c5dbb03cf65aebce48b0ee2f1cbf55c')
    ])
    
    # Insert mock chat data
    mock_messages = [
        ('general', 'admin', 'Welcome to the corporate chat server!'),
        ('general', 'alice', 'Hi everyone, glad to be here.'),
        ('helpdesk', 'bob', 'Can someone reset my VPN credentials?'),
        ('helpdesk', 'admin', 'I will send you a DM with the reset link.'),
        ('watercooler', 'alice', 'Anyone want to grab lunch at 12?')
    ]
    
    cursor.executemany('''
        INSERT INTO messages (room_name, sender, content)
        VALUES (?, ?, ?)
    ''', mock_messages)
    
    conn.commit()
    conn.close()
    logger.info("Chat database initialized successfully with mock data.")

def log_new_message(room_name, sender, content):
    """Securely logs a new message to the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO messages (room_name, sender, content)
            VALUES (?, ?, ?)
        ''', (room_name, sender, content))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Failed to log message: {e}")
    finally:
        conn.close()

def retrieve_room_history(room_name):
    """
    VULNERABLE FUNCTION: CWE-89 SQL Injection
    Trigger Path: WebSocket JSON payload parsing (action: get_history -> room parameter)
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Vulnerability: Direct string concatenation of the WebSocket JSON parameter into the SQL query
    query = f"SELECT sender, content, timestamp FROM messages WHERE room_name = '{room_name}' ORDER BY timestamp DESC LIMIT 20"
    
    try:
        logger.info(f"Executing query for room history: {query}")
        cursor.execute(query)
        records = cursor.fetchall()
        
        history = []
        for row in records:
            history.append({
                "sender": row[0],
                "content": row[1],
                "timestamp": row[2]
            })
        return {"status": "success", "data": history}
        
    except sqlite3.Error as e:
        logger.error(f"Database error during history retrieval: {e}")
        # Leaking the database error aids exploitation over the WebSocket connection
        return {"status": "error", "message": f"Database query failed: {e}"}
    finally:
        conn.close()

async def handle_client_connection(websocket):
    client_address = websocket.remote_address
    logger.info(f"New client connected from {client_address}")
    
    try:
        async for message in websocket:
            logger.debug(f"Received raw WebSocket message: {message}")
            
            try:
                # The payload is received over WebSockets as a JSON string
                payload = json.loads(message)
                action = payload.get("action")
                
                if action == "send_message":
                    room = payload.get("room", "general")
                    sender = payload.get("sender", "anonymous")
                    content = payload.get("content", "")
                    
                    if content:
                        log_new_message(room, sender, content)
                        await websocket.send(json.dumps({"status": "success", "message": "Message sent"}))
                    else:
                        await websocket.send(json.dumps({"status": "error", "message": "Empty content"}))
                        
                elif action == "get_history":
                    room = payload.get("room", "")
                    if not room:
                        await websocket.send(json.dumps({"status": "error", "message": "Room name required"}))
                        continue
                        
                    # Triggering the vulnerable function with the parsed JSON value
                    result = retrieve_room_history(room)
                    await websocket.send(json.dumps(result))
                    
                elif action == "ping":
                    await websocket.send(json.dumps({"status": "success", "message": "pong"}))
                    
                else:
                    await websocket.send(json.dumps({"status": "error", "message": "Unknown action"}))
                    
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"status": "error", "message": "Invalid JSON format"}))
                
    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"Client {client_address} disconnected. Reason: {e}")
    except Exception as e:
        logger.error(f"Unexpected error with client {client_address}: {e}")

async def main():
    initialize_chat_database()
    
    # Start the WebSocket server
    server = await websockets.serve(
        handle_client_connection, 
        "localhost", 
        8765
    )
    
    logger.info("WebSocket Chat Server is running on ws://localhost:8765")
    await server.wait_closed()

if __name__ == "__main__":
    # Example Malicious WebSocket Payload from client:
    # {
    #     "action": "get_history",
    #     "room": "general' UNION SELECT username, password_hash, role FROM users--"
    # }
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server shutting down gracefully.")
