import xmlrpc.server
from xmlrpc.server import SimpleXMLRPCServer
from xmlrpc.server import SimpleXMLRPCRequestHandler
import logging
import sys
import uuid
from datetime import datetime

# Setup logging for the Pipeline Orchestrator
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('PipelineOrchestrator')

# Mock In-Memory Data Warehouse
DATA_WAREHOUSE = {
    'sales_data_q1': [
        {'item': 'widget_a', 'qty': 150, 'price': 12.50}, 
        {'item': 'widget_b', 'qty': 80, 'price': 45.00}
    ],
    'employee_roster': [
        {'emp_id': 101, 'department': 'Engineering', 'status': 'active'}, 
        {'emp_id': 102, 'department': 'Sales', 'status': 'on_leave'}
    ],
    'server_logs': [
        {'timestamp': '2023-10-01T10:00:00', 'level': 'INFO', 'msg': 'Service started'},
        {'timestamp': '2023-10-01T10:05:22', 'level': 'ERROR', 'msg': 'Connection timeout'}
    ]
}

# Audit trail for executed jobs
JOB_HISTORY = []

class CustomRequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/RPC2',)

class ETLNodeProcessor:
    """
    Handles Extract, Transform, Load operations via XML-RPC.
    Allows remote clients to process datasets stored in the warehouse.
    """
    def __init__(self):
        self.node_startup_time = datetime.now()

    def get_system_status(self):
        """Returns basic health and uptime metrics"""
        return {
            "status": "Operational",
            "uptime_seconds": (datetime.now() - self.node_startup_time).total_seconds(),
            "available_datasets": list(DATA_WAREHOUSE.keys())
        }

    def fetch_job_history(self, limit=5):
        """Returns the most recent executed jobs"""
        return JOB_HISTORY[-limit:]

    def run_standard_aggregation(self, source_name, agg_type):
        """Runs safe, hardcoded data aggregations"""
        if source_name not in DATA_WAREHOUSE:
            return {"error": "Target data source not found"}
        
        data = DATA_WAREHOUSE[source_name]
        job_id = f"job_std_{uuid.uuid4().hex[:6]}"
        
        try:
            if agg_type == 'record_count':
                result = len(data)
            elif agg_type == 'sum_qty' and source_name == 'sales_data_q1':
                result = sum(item.get('qty', 0) for item in data)
            else:
                return {"error": "Unsupported aggregation type or incompatible source"}
                
            JOB_HISTORY.append({"job_id": job_id, "type": "standard", "status": "success"})
            return {"job_id": job_id, "result": result}
            
        except Exception as e:
            JOB_HISTORY.append({"job_id": job_id, "type": "standard", "status": "failed"})
            return {"error": str(e)}

    def execute_custom_transformation(self, source_name, transform_rules, job_metadata):
        """
        FIXED: CWE-94 Code Injection mitigated by removing exec().
        Replaced arbitrary script execution with a safe, structured rule-based transformation engine.
        """
        logger.info(f"Initiating safe ETL transformation on '{source_name}'")
        
        if source_name not in DATA_WAREHOUSE:
            return {"error": f"Data source '{source_name}' does not exist."}
            
        job_id = f"job_cst_{uuid.uuid4().hex[:6]}"
        dataset = DATA_WAREHOUSE[source_name]
        
        try:
            # FIXED SINK: Removed exec(). Now interpreting a structured list of rules.
            # Example transform_rules payload:
            # [{"action": "filter", "field": "status", "operator": "eq", "value": "active"},
            #  {"action": "extract", "fields": ["emp_id", "department"]}]
            
            if not isinstance(transform_rules, list):
                return {"error": "transform_rules must be a list of operation dictionaries."}
                
            transformed_data = dataset.copy()
            
            for rule in transform_rules:
                action = rule.get("action")
                
                if action == "filter":
                    field = rule.get("field")
                    value = rule.get("value")
                    op = rule.get("operator", "eq")
                    
                    if op == "eq":
                        transformed_data = [row for row in transformed_data if row.get(field) == value]
                    elif op == "ne":
                        transformed_data = [row for row in transformed_data if row.get(field) != value]
                    else:
                        return {"error": f"Unsupported filter operator: {op}"}
                        
                elif action == "extract":
                    fields = rule.get("fields", [])
                    if not isinstance(fields, list):
                        return {"error": "extract action requires a list of fields"}
                    transformed_data = [{k: row.get(k) for k in fields if k in row} for row in transformed_data]
                    
                elif action == "add_field":
                    field = rule.get("field")
                    val = rule.get("value")
                    if field:
                        for row in transformed_data:
                            row[field] = val
                            
                else:
                    return {"error": f"Unsupported transformation action: {action}"}
            
            JOB_HISTORY.append({
                "job_id": job_id, 
                "type": "custom", 
                "metadata": job_metadata,
                "status": "success"
            })
            
            return {
                "status": "success",
                "job_id": job_id,
                "records_processed": len(dataset),
                "result_preview": transformed_data[:5] if isinstance(transformed_data, list) else transformed_data
            }
            
        except Exception as e:
            logger.error(f"Safe custom transformation failed: {str(e)}")
            JOB_HISTORY.append({
                "job_id": job_id, 
                "type": "custom", 
                "status": "failed",
                "error": str(e)
            })
            return {
                "status": "error", 
                "message": "Transformation encountered an exception.", 
                "details": str(e)
            }

def start_server():
    host = '0.0.0.0'
    port = 9000
    logger.info(f"Starting XML-RPC ETL Pipeline Orchestrator on {host}:{port}")
    
    # allow_none=True allows passing None values across XML-RPC
    with SimpleXMLRPCServer((host, port), requestHandler=CustomRequestHandler, allow_none=True) as server:
        # Registers system.listMethods, system.methodHelp, system.methodSignature
        server.register_introspection_functions()
        
        # Bind the processor instance to the RPC server
        node_processor = ETLNodeProcessor()
        server.register_instance(node_processor)
        
        try:
            logger.info("Server is running and listening for RPC calls...")
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("Shutdown signal received. Stopping server...")
            sys.exit(0)

if __name__ == '__main__':
    start_server()
