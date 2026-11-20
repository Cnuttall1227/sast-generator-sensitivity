import socketserver
import threading
import sqlite3
import os
import logging
import time

# Configure logging for the High-Frequency Trading TCP Router
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - TradeRouterTCP - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TradeRouterTCP")

DB_FILE = "trade_routing_engine.db"
PORT = 8888

def setup_trading_database():
    """Initializes the local SQLite database for the trading engine."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create active orders table
    cursor.execute('''
        CREATE TABLE active_orders (
            order_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            status TEXT NOT NULL
        )
    ''')
    
    # Create highly sensitive internal system credentials table
    cursor.execute('''
        CREATE TABLE system_credentials (
            service_name TEXT PRIMARY KEY,
            clearance_level TEXT NOT NULL,
            auth_token TEXT NOT NULL
        )
    ''')
    
    # Populate mock active orders
    mock_orders = [
        ('ORD-001', 'AAPL', 100, 'FILLED'),
        ('ORD-002', 'TSLA', 50, 'PENDING'),
        ('ORD-003', 'MSFT', 200, 'REJECTED'),
        ('ORD-004', 'NVDA', 10, 'ROUTED_TO_DARKPOOL')
    ]
    cursor.executemany('''
        INSERT INTO active_orders (order_id, symbol, quantity, status)
        VALUES (?, ?, ?, ?)
    ''', mock_orders)
    
    # Populate sensitive system credentials
    mock_credentials = [
        ('CLEARING_HOUSE_API', 'TIER_1', 'tok_prod_8819238912'),
        ('DARK_POOL_ACCESS', 'TIER_0', 'tok_dp_secret_99812'),
        ('MARKET_MAKER_GW', 'TIER_1', 'tok_mm_112233')
    ]
    cursor.executemany('''
        INSERT INTO system_credentials (service_name, clearance_level, auth_token)
        VALUES (?, ?, ?)
    ''', mock_credentials)
    
    conn.commit()
    conn.close()
    logger.info("Trading database initialized with active orders and system secrets.")


def check_order_status(order_id: str):
    """
    VULNERABLE FUNCTION: CWE-89 SQL Injection
    Trigger Path: Custom TCP Socket Protocol message parsing (pipe-delimited string)
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Vulnerability: Direct string concatenation of the TCP payload into the SQL query
    query = f"SELECT symbol, quantity, status FROM active_orders WHERE order_id = '{order_id}'"
    
    try:
        logger.debug(f"Executing internal database query: {query}")
        cursor.execute(query)
        record = cursor.fetchone()
        
        if record:
            # Format successful response using the custom protocol syntax
            return f"STATUS|{record[0]}|{record[1]}|{record[2]}"
            
        return "ERROR|ORDER_NOT_FOUND"
        
    except sqlite3.Error as e:
        logger.error(f"Database error during order lookup: {e}")
        # Leaking the database error directly back over the raw TCP socket
        # allows an attacker to map the database schema via error-based SQL injection
        return f"FATAL_DB_ERROR|{e}"
    finally:
        conn.close()


class TradeProtocolHandler(socketserver.BaseRequestHandler):
    """Handles incoming raw TCP connections using a custom pipe-delimited protocol."""
    
    def handle(self):
        client_ip = self.client_address[0]
        logger.info(f"New TCP connection established from {client_ip}")
        
        try:
            while True:
                # Read up to 1024 bytes from the TCP socket
                data = self.request.recv(1024)
                if not data:
                    break
                
                message = data.decode('utf-8').strip()
                logger.debug(f"Received raw TCP message: {message}")
                
                # Custom Protocol Format Expected: INQUIRY|<ORDER_ID>
                parts = message.split('|')
                
                if len(parts) >= 2 and parts[0] == "INQUIRY":
                    # Extract the untrusted order_id payload from the TCP stream
                    order_id_payload = parts[1]
                    
                    # Pass the untrusted data to the vulnerable database function
                    response = check_order_status(order_id_payload)
                    
                    # Transmit the result back to the TCP client
                    self.request.sendall((response + "\n").encode('utf-8'))
                    
                else:
                    logger.warning(f"Invalid protocol format received from {client_ip}")
                    self.request.sendall(b"ERROR|INVALID_FORMAT\n")
                    
        except ConnectionResetError:
            logger.warning(f"Connection reset by peer {client_ip}")
        except Exception as e:
            logger.error(f"Unexpected connection error handling {client_ip}: {e}")
        finally:
            logger.info(f"TCP connection closed for {client_ip}")


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Allows multiple clients to connect asynchronously via threading."""
    daemon_threads = True
    allow_reuse_address = True


def start_trading_server():
    """Configures and launches the TCP Socket server."""
    setup_trading_database()
    
    server = ThreadedTCPServer(("0.0.0.0", PORT), TradeProtocolHandler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    logger.info(f"Trade Router TCP Server listening on 0.0.0.0:{PORT}")
    
    # Example exploitation via netcat (nc) to inject SQL over the raw TCP socket:
    # echo "INQUIRY|ORD-001' UNION SELECT service_name, auth_token, clearance_level FROM system_credentials--" | nc localhost 8888
    
    try:
        # Keep the main thread alive while the daemon handles TCP connections
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down the TCP Trade Router server.")
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    start_trading_server()
