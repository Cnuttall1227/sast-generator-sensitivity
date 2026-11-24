import asyncio
import websockets
import sqlite3
import json
import os
import logging

# Configure logging for the WebSocket Service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - CryptoWS - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CryptoExchangeWebSocket")

DB_FILE = "crypto_exchange.db"
WS_HOST = "127.0.0.1"
WS_PORT = 8765

def initialize_database():
    """Initializes the local SQLite database with wallets and sensitive audit logs."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Create public wallets table
    cursor.execute('''
        CREATE TABLE wallets (
            wallet_id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT NOT NULL,
            asset_symbol TEXT NOT NULL,
            balance REAL NOT NULL,
            status TEXT NOT NULL
        )
    ''')

    # Create highly sensitive internal audit log table
    cursor.execute('''
        CREATE TABLE admin_audit_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            details TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Populate standard user wallets
    mock_wallets = [
        ('USER-KEY-1001', 'BTC', 2.5, 'ACTIVE'),
        ('USER-KEY-1001', 'ETH', 14.2, 'ACTIVE'),
        ('USER-KEY-2044', 'USDT', 5000.0, 'ACTIVE'),
        ('USER-KEY-2044', 'SOL', 150.0, 'FROZEN')
    ]
    cursor.executemany('''
        INSERT INTO wallets (api_key, asset_symbol, balance, status)
        VALUES (?, ?, ?, ?)
    ''', mock_wallets)

    # Populate sensitive admin logs
    mock_logs = [
        ('ADMIN-ROOT', 'MANUAL_OVERRIDE', 'Disabled withdrawal limits for VIP-992'),
        ('ADMIN-SEC', 'KEY_ROTATION', 'Cold wallet master seed updated to: vault-alpha-99x'),
        ('ADMIN-ROOT', 'USER_BAN', 'Suspended USER-KEY-8812 due to wash trading')
    ]
    cursor.executemany('''
        INSERT INTO admin_audit_log (admin_id, action_type, details)
        VALUES (?, ?, ?)
    ''', mock_logs)

    conn.commit()
    conn.close()
    logger.info("Exchange database initialized with mock wallet and audit data.")

def fetch_wallet_balance(api_key: str):
    """
    VULNERABLE FUNCTION: CWE-89 SQL Injection
    Trigger Path: WebSocket incoming message parsing (extracting from JSON payload)
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Vulnerability: Direct string concatenation of the WebSocket parsed value into the SQL query
    query = f"SELECT asset_symbol, balance, status FROM wallets WHERE api_key = '{api_key}'"

    try:
        logger.info(f"Executing wallet lookup query: {query}")
        cursor.execute(query)
        records = cursor.fetchall()

        if records:
            return [{"asset": row[0], "balance": row[1], "status": row[2]} for row in records]
        return []
    except sqlite3.Error as e:
        logger.error(f"Database error during wallet lookup: {e}")
        # Leaking the database error in the WebSocket response allows error-based SQL injection mapping
        return {"error": f"SQL Error: {e}"}
    finally:
        conn.close()

def process_secure_trade(api_key: str, symbol: str, amount: float):
    """Securely executes a mock trade using parameterized queries."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            UPDATE wallets SET balance = balance + ? 
            WHERE api_key = ? AND asset_symbol = ?
        ''', (amount, api_key, symbol))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"Trade processing error: {e}")
        return False
    finally:
        conn.close()

async def handle_client(websocket):
    """Handles incoming WebSocket connections and parses JSON action frames."""
    remote_ip = websocket.remote_address[0] if websocket.remote_address else "Unknown"
    logger.info(f"New client connected from {remote_ip}")
    try:
        async for message in websocket:
            try:
                payload = json.loads(message)
                action = payload.get("action")
                logger.debug(f"Received action '{action}' from {remote_ip}")

                if action == "get_balance":
                    api_key = payload.get("api_key")
                    if not api_key:
                        await websocket.send(json.dumps({"status": "error", "message": "Missing api_key"}))
                        continue

                    # Triggering the vulnerable function via data extracted from the WebSocket payload
                    balance_data = fetch_wallet_balance(api_key)
                    
                    if isinstance(balance_data, dict) and "error" in balance_data:
                        await websocket.send(json.dumps({"status": "error", "message": balance_data["error"]}))
                    else:
                        await websocket.send(json.dumps({"status": "success", "data": balance_data}))

                elif action == "execute_trade":
                    api_key = payload.get("api_key")
                    symbol = payload.get("symbol")
                    amount = payload.get("amount")
                    
                    if not all([api_key, symbol, amount]):
                        await websocket.send(json.dumps({"status": "error", "message": "Missing trade parameters"}))
                        continue
                        
                    success = process_secure_trade(api_key, symbol, float(amount))
                    if success:
                        await websocket.send(json.dumps({"status": "success", "message": f"Trade executed for {symbol}"}))
                    else:
                        await websocket.send(json.dumps({"status": "error", "message": "Trade failed"}))
                        
                else:
                    await websocket.send(json.dumps({"status": "error", "message": "Unknown action"}))

            except json.JSONDecodeError:
                await websocket.send(json.dumps({"status": "error", "message": "Invalid JSON payload format"}))
            except Exception as e:
                logger.error(f"Unexpected error handling message: {e}")
                await websocket.send(json.dumps({"status": "error", "message": "Internal server error"}))

    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Client {remote_ip} disconnected cleanly")
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")

async def start_server():
    """Starts the asynchronous WebSocket server."""
    initialize_database()
    
    logger.info(f"Starting Crypto Exchange WebSocket API on ws://{WS_HOST}:{WS_PORT}")
    async with websockets.serve(handle_client, WS_HOST, WS_PORT):
        await asyncio.Future()  # run forever to keep the server alive

if __name__ == "__main__":
    # Example Malicious WebSocket payload (send as a text frame from a WS client):
    # {
    #   "action": "get_balance", 
    #   "api_key": "USER-KEY-1001' UNION SELECT action_type, details, 'LEAKED' FROM admin_audit_log WHERE admin_id='ADMIN-SEC'--"
    # }
    
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.info("Shutting down WebSocket server.")
