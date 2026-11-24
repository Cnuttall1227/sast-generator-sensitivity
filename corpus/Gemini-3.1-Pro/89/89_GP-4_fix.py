import asyncio
import sqlite3
import logging
import os
import random
from datetime import datetime

# Configure logging for the IoT server
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("IoT_Telemetry_Server")

DB_FILE = "iot_telemetry.db"

def setup_database():
    """Initializes the SQLite database with devices and telemetry data."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create devices table
    cursor.execute('''
        CREATE TABLE devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mac_address TEXT UNIQUE NOT NULL,
            firmware_version TEXT NOT NULL,
            status TEXT NOT NULL
        )
    ''')
    
    # Create telemetry data table
    cursor.execute('''
        CREATE TABLE telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mac_address TEXT NOT NULL,
            temperature REAL,
            humidity REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (mac_address) REFERENCES devices(mac_address)
        )
    ''')
    
    sample_devices = [
        ('00:1B:44:11:3A:B7', 'v1.2.0', 'active'),
        ('00:1B:44:11:3A:B8', 'v1.2.1', 'active'),
        ('00:1B:44:11:3A:B9', 'v1.1.0', 'maintenance'),
        ('AA:BB:CC:DD:EE:FF', 'v2.0.0', 'active')
    ]
    
    cursor.executemany('''
        INSERT INTO devices (mac_address, firmware_version, status) 
        VALUES (?, ?, ?)
    ''', sample_devices)
    
    # Generate some mock telemetry data
    for mac, _, _ in sample_devices:
        for _ in range(5):
            temp = round(random.uniform(20.0, 35.0), 2)
            hum = round(random.uniform(40.0, 60.0), 2)
            cursor.execute('''
                INSERT INTO telemetry (mac_address, temperature, humidity) 
                VALUES (?, ?, ?)
            ''', (mac, temp, hum))
            
    conn.commit()
    conn.close()
    logger.info("IoT Database initialized successfully with mock data.")

class TelemetryServer(asyncio.Protocol):
    def connection_made(self, transport):
        self.transport = transport
        self.peername = transport.get_extra_info('peername')
        logger.info(f"Connection established from {self.peername}")

    def data_received(self, data):
        message = data.decode().strip()
        logger.debug(f"Received raw socket data: {message}")
        
        try:
            # Custom Protocol: COMMAND|PAYLOAD
            command, payload = message.split("|", 1)
            
            if command == "PING":
                self.transport.write(b"PONG\n")
            elif command == "REPORT":
                # Payload is expected to be a device mac_address
                response = self.generate_device_report(payload)
                self.transport.write(f"{response}\n".encode())
            elif command == "INGEST":
                self.transport.write(b"ACK_INGEST\n")
            else:
                self.transport.write(b"ERROR: Unknown command\n")
        except ValueError:
            self.transport.write(b"ERROR: Invalid protocol format. Use COMMAND|PAYLOAD\n")
        except Exception as e:
            logger.error(f"Error processing data: {e}")
            self.transport.write(b"ERROR: Internal Server Error\n")

    def generate_device_report(self, mac_address):
        """
        SECURE: Uses parameterized queries (?) to prevent SQL Injection
        """
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Secure parameterized query
        query = "SELECT temperature, humidity, timestamp FROM telemetry WHERE mac_address = ? ORDER BY timestamp DESC LIMIT 3"
        
        try:
            logger.info(f"Executing secure database query for device: {mac_address}")
            cursor.execute(query, (mac_address,))
            records = cursor.fetchall()
            
            if not records:
                return f"NO_DATA for device {mac_address}"
            
            report_lines = [f"REPORT_FOR_DEVICE:{mac_address}"]
            for temp, hum, ts in records:
                report_lines.append(f"[{ts}] TEMP:{temp}C HUM:{hum}%")
                
            return "\n".join(report_lines)
            
        except sqlite3.Error as e:
            logger.error(f"Database execution error: {e}")
            return f"DB_ERROR: {e}"
        finally:
            conn.close()
            
    def connection_lost(self, exc):
        logger.info(f"Connection closed from {self.peername}")

async def main():
    setup_database()
    
    loop = asyncio.get_running_loop()
    server = await loop.create_server(
        lambda: TelemetryServer(),
        '127.0.0.1', 8888
    )
    
    logger.info("Serving IoT Telemetry TCP Service on 127.0.0.1:8888")
    
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("IoT Server stopped gracefully by user.")
