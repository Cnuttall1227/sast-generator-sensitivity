import asyncio
import websockets
import json
import logging
from collections import defaultdict
import time
import math

# Configure logging for the WebSocket server
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('IoT_Telemetry_Hub')

# In-memory database to store recent telemetry points
telemetry_store = defaultdict(list)
connected_clients = set()
server_stats = {
    "total_messages": 0, 
    "errors": 0, 
    "start_time": time.time()
}

def get_system_uptime():
    """Returns the server uptime in seconds."""
    return time.time() - server_stats["start_time"]

async def register_client(websocket):
    """Registers a new WebSocket client and sends a welcome message."""
    connected_clients.add(websocket)
    logger.info(f"Client connected. Total clients: {len(connected_clients)}")
    try:
        await websocket.send(json.dumps({
            "type": "welcome", 
            "uptime_seconds": get_system_uptime(),
            "message": "Connected to IoT Telemetry Hub"
        }))
    except websockets.exceptions.ConnectionClosed:
        pass

async def unregister_client(websocket):
    """Unregisters a WebSocket client upon disconnect."""
    connected_clients.remove(websocket)
    logger.info(f"Client disconnected. Total clients: {len(connected_clients)}")

def execute_dynamic_aggregation(device_id, aggregation_rule):
    """
    FIXED: CWE-94 Code Injection mitigated by removing eval().
    Replaced arbitrary Python code execution with a secure, structured aggregation engine.
    """
    if device_id not in telemetry_store:
        return {"error": f"No data available for device '{device_id}'"}
        
    dataset = telemetry_store[device_id]
    
    try:
        # FIXED SINK: Removed eval() entirely.
        # We now expect aggregation_rule to be a structured dictionary instead of a raw string.
        # Example payload: {"type": "average", "field": "val"}
        
        if not isinstance(aggregation_rule, dict):
            return {"error": "Aggregation rule must be a structured JSON object."}
            
        agg_type = aggregation_rule.get("type")
        field = aggregation_rule.get("field", "val")
        
        # Safely extract numeric values for the requested field
        values = [d.get(field) for d in dataset if isinstance(d.get(field), (int, float))]
        
        if not values:
            return {"error": f"No valid numeric data found for field '{field}' to aggregate."}
            
        # Apply predefined, safe aggregation operations
        if agg_type == "sum":
            result = sum(values)
        elif agg_type in ("average", "mean"):
            result = sum(values) / len(values)
        elif agg_type == "max":
            result = max(values)
        elif agg_type == "min":
            result = min(values)
        elif agg_type == "count":
            result = len(values)
        else:
            return {"error": f"Unsupported aggregation type: {agg_type}"}
        
        return {
            "status": "success", 
            "records_processed": len(dataset),
            "aggregated_value": result,
            "applied_rule": agg_type
        }
    except Exception as e:
        logger.error(f"Safe aggregation failed for {device_id}: {str(e)}")
        return {
            "status": "error", 
            "message": "Aggregation runtime error."
        }

async def process_message(websocket, message):
    """Routes incoming WebSocket messages based on their 'action' field."""
    server_stats["total_messages"] += 1
    
    try:
        data = json.loads(message)
        action = data.get("action")

        if action == "ingest":
            # IoT Devices send telemetry data to this endpoint
            device_id = data.get("device_id")
            payload = data.get("payload", {})
            
            if device_id and payload:
                value = float(payload.get('value', 0.0))
                sensor_type = payload.get('sensor', 'unknown')
                
                record = {"ts": time.time(), "val": value, "sensor": sensor_type}
                telemetry_store[device_id].append(record)
                
                # Retain only the most recent 100 records per device to prevent memory bloat
                if len(telemetry_store[device_id]) > 100:
                    telemetry_store[device_id].pop(0)
                    
                await websocket.send(json.dumps({"type": "ack", "status": "ingested"}))
            else:
                await websocket.send(json.dumps({"type": "error", "msg": "Missing device_id or payload"}))

        elif action == "aggregate":
            # Data analysts request aggregated views using custom mathematical rules
            device_id = data.get("device_id")
            rule = data.get("rule")
            
            if device_id and rule:
                logger.info(f"Running dynamic aggregation for {device_id}: {rule}")
                result = execute_dynamic_aggregation(device_id, rule)
                await websocket.send(json.dumps({"type": "aggregation_result", "data": result}))
            else:
                await websocket.send(json.dumps({"type": "error", "msg": "Missing device_id or rule for aggregation"}))
                
        elif action == "stats":
            # Returns operational metrics of the hub
            await websocket.send(json.dumps({"type": "stats", "data": server_stats}))
            
        else:
            await websocket.send(json.dumps({"type": "error", "msg": f"Unknown action: {action}"}))

    except json.JSONDecodeError:
        server_stats["errors"] += 1
        await websocket.send(json.dumps({"type": "error", "msg": "Payload must be valid JSON"}))
    except Exception as e:
        server_stats["errors"] += 1
        logger.error(f"Error processing message: {str(e)}")
        await websocket.send(json.dumps({"type": "error", "msg": "Internal server error during message processing"}))

async def websocket_handler(websocket, path):
    """Main coroutine handling the lifecycle of a single WebSocket connection."""
    await register_client(websocket)
    try:
        async for message in websocket:
            await process_message(websocket, message)
    except websockets.exceptions.ConnectionClosedError:
        logger.warning("Client connection closed abruptly")
    finally:
        await unregister_client(websocket)

async def main():
    """Initializes and starts the asyncio WebSocket server."""
    host = "0.0.0.0"
    port = 8765
    logger.info(f"Starting IoT Telemetry Hub WebSocket Server on ws://{host}:{port}")
    
    # Start the WebSocket server and bind it to the handler
    async with websockets.serve(websocket_handler, host, port):
        # Keep the event loop running forever
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupt received. Server shutting down gracefully.")
