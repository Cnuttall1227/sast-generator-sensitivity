import socketserver
import threading
import logging
import json
import sys
from datetime import datetime
from collections import deque

# Configure logging for the Log Aggregator service
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TcpLogAggregator")

# In-memory storage for logs, retaining only the most recent entries
MAX_LOG_HISTORY = 1000
log_buffer = deque(maxlen=MAX_LOG_HISTORY)

# System metrics for monitoring
metrics = {
    "connections_handled": 0,
    "logs_ingested": 0,
    "queries_executed": 0,
    "errors": 0
}

class LogAggregatorProtocol(socketserver.StreamRequestHandler):
    """
    Custom TCP protocol handler for internal log aggregation.
    Supported Commands:
    - INGEST <json_payload>
    - STATS
    - QUERY <python_expression>
    - QUIT
    """
    def handle(self):
        client_ip = self.client_address[0]
        logger.info(f"New connection established from {client_ip}")
        metrics["connections_handled"] += 1
        
        # Send greeting
        self.wfile.write(b"Welcome to the Internal TCP Log Aggregator.\n")

        while True:
            try:
                line = self.rfile.readline()
                if not line:
                    break
                
                decoded_line = line.decode('utf-8').strip()
                if not decoded_line:
                    continue

                # Parse the custom protocol command
                parts = decoded_line.split(" ", 1)
                command = parts[0].upper()
                payload = parts[1] if len(parts) > 1 else ""

                if command == "QUIT":
                    self.wfile.write(b"Goodbye.\n")
                    break
                elif command == "INGEST":
                    self.process_ingest(payload)
                elif command == "STATS":
                    self.process_stats()
                elif command == "QUERY":
                    self.process_diagnostic_query(payload)
                else:
                    self.wfile.write(b"ERR: Unknown command.\n")

            except Exception as e:
                logger.error(f"Error handling connection from {client_ip}: {e}")
                metrics["errors"] += 1
                try:
                    self.wfile.write(f"ERR: Internal server error {e}\n".encode('utf-8'))
                except Exception:
                    pass
                break
                
        logger.info(f"Connection closed for {client_ip}")

    def process_ingest(self, payload):
        """Parses and stores incoming log entries"""
        try:
            log_entry = json.loads(payload)
            log_entry["_server_time"] = datetime.utcnow().isoformat()
            log_buffer.append(log_entry)
            metrics["logs_ingested"] += 1
            self.wfile.write(b"OK: Log ingested.\n")
        except json.JSONDecodeError:
            metrics["errors"] += 1
            self.wfile.write(b"ERR: Invalid JSON payload for INGEST.\n")

    def process_stats(self):
        """Returns server health and statistics"""
        stats_output = json.dumps(metrics) + "\n"
        self.wfile.write(stats_output.encode('utf-8'))

    def process_diagnostic_query(self, payload):
        """
        FIXED: CWE-94 Code Injection mitigated by removing eval().
        Replaced arbitrary Python code execution with a secure, structured JSON-based filtering system.
        """
        logger.info(f"Executing secure diagnostic query: {payload}")
        metrics["queries_executed"] += 1
        
        if not payload:
            self.wfile.write(b"ERR: Query payload cannot be empty.\n")
            return

        try:
            # FIXED SINK: Removed eval() entirely.
            # We now expect a structured JSON payload for querying.
            # Example payload: {"field": "level", "operator": "eq", "value": "ERROR"}
            query_params = json.loads(payload)
            
            if not isinstance(query_params, dict):
                self.wfile.write(b"ERR: Query must be a valid JSON object.\n")
                return
                
            field = query_params.get("field")
            operator_str = query_params.get("operator", "eq")
            value = query_params.get("value")
            
            if not field or value is None:
                self.wfile.write(b"ERR: Query must include 'field' and 'value' keys.\n")
                return

            current_logs = list(log_buffer)
            
            # Safely filter logs based on the provided JSON parameters without executing code
            result = []
            for log in current_logs:
                log_value = log.get(field)
                
                if log_value is None:
                    continue
                    
                # Safe, hardcoded comparisons
                if operator_str == "eq" and log_value == value:
                    result.append(log)
                elif operator_str == "ne" and log_value != value:
                    result.append(log)
                elif operator_str == "contains" and isinstance(log_value, str) and str(value) in log_value:
                    result.append(log)
            
            # Format the output back to the TCP client
            response = {
                "status": "success",
                "match_count": len(result),
                "results": result
            }
            
            self.wfile.write((json.dumps(response) + "\n").encode('utf-8'))
            
        except json.JSONDecodeError:
            metrics["errors"] += 1
            self.wfile.write(b"ERR: Invalid JSON payload for QUERY.\n")
        except Exception as e:
            logger.error(f"Query execution failed: {str(e)}")
            metrics["errors"] += 1
            self.wfile.write(f"ERR: Query execution failed - {str(e)}\n".encode('utf-8'))


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Allows multiple clients to connect asynchronously"""
    daemon_threads = True
    allow_reuse_address = True


def pre_populate_logs():
    """Adds initial telemetry data for query testing"""
    log_buffer.append({"level": "INFO", "service": "auth", "msg": "Node started", "uid": 0})
    log_buffer.append({"level": "ERROR", "service": "db_sync", "msg": "Sync timeout", "retry": 1})
    log_buffer.append({"level": "WARN", "service": "api", "msg": "High latency detected", "ms": 450})
    metrics["logs_ingested"] += 3


if __name__ == "__main__":
    pre_populate_logs()
    
    # Binds to all interfaces, exposing the vulnerable TCP port to the network
    HOST, PORT = "0.0.0.0", 8443
    server = ThreadedTCPServer((HOST, PORT), LogAggregatorProtocol)
    
    logger.info(f"Log Aggregator TCP Server running on {HOST}:{PORT}")
    logger.info(f"Connect using netcat: nc 127.0.0.1 {PORT}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutdown signal received. Closing server.")
        server.server_close()
        sys.exit(0)
