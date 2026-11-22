import logging
import json
import os
import sys
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, abort

# Configure logging for the application
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('AdvancedDataProcessor')

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-environment-key-99812'
app.config['DEBUG'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

# In-memory mock database for system configurations and user data
SYSTEM_DB = {
    'clients': {
        'client_a': {'tier': 'enterprise', 'features': ['standard', 'custom_eval']},
        'client_b': {'tier': 'basic', 'features': ['standard']}
    },
    'metrics': {
        'total_requests': 0,
        'failed_requests': 0
    }
}

def require_auth(f):
    """Decorator to enforce basic API key authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-Processor-Token')
        if not api_key or api_key != 'svc-token-88492':
            logger.warning(f"Unauthorized access attempt from {request.remote_addr}")
            SYSTEM_DB['metrics']['failed_requests'] += 1
            abort(401, description="Missing or invalid authentication token")
        return f(*args, **kwargs)
    return decorated

@app.route('/system/status', methods=['GET'])
def system_status():
    """Endpoint to check the health and metrics of the API"""
    return jsonify({
        'service': 'AdvancedDataProcessor',
        'status': 'online',
        'server_time': datetime.now().isoformat(),
        'metrics': SYSTEM_DB['metrics']
    })

def apply_standard_metrics(data_payload, action_type):
    """Safe, predefined data transformations"""
    logger.info(f"Running standard action: {action_type}")
    if action_type == 'aggregate_sum':
        return sum(data_payload)
    elif action_type == 'find_max':
        return max(data_payload) if data_payload else None
    elif action_type == 'find_min':
        return min(data_payload) if data_payload else None
    return data_payload

@app.route('/api/v1/data/standard', methods=['POST'])
@require_auth
def process_standard():
    """Processes data using safe, hardcoded mathematical operations"""
    SYSTEM_DB['metrics']['total_requests'] += 1
    req_data = request.get_json()
    
    if not req_data or 'dataset' not in req_data or 'action' not in req_data:
        return jsonify({'error': 'Malformed request. Missing dataset or action.'}), 400

    dataset = req_data['dataset']
    action = req_data['action']

    if not isinstance(dataset, list):
        return jsonify({'error': 'Dataset must be an array of numeric values.'}), 400

    try:
        result = apply_standard_metrics(dataset, action)
        return jsonify({'status': 'success', 'result': result, 'action_applied': action})
    except Exception as e:
        logger.error(f"Standard processing error: {e}")
        return jsonify({'error': 'Failed to process dataset.'}), 500

@app.route('/api/v1/data/dynamic', methods=['POST'])
@require_auth
def process_dynamic():
    """
    Processes data using a safe, structured query approach instead of arbitrary code execution.
    FIXED: CWE-94 Code Injection mitigated by removing eval() and using predefined operations.
    """
    SYSTEM_DB['metrics']['total_requests'] += 1
    req_data = request.get_json()
    
    # Require a structured dictionary format instead of a raw Python string
    if not req_data or 'dataset' not in req_data or 'operation' not in req_data:
        return jsonify({'error': 'Malformed request. Missing dataset or operation.'}), 400

    dataset = req_data['dataset']
    operation = req_data['operation']
    client_id = req_data.get('client_id', 'unknown')

    if not isinstance(dataset, list):
        return jsonify({'error': 'Dataset must be an array of numeric values.'}), 400

    if not isinstance(operation, dict):
        return jsonify({'error': 'Operation must be a JSON object containing "type" and "value".'}), 400

    logger.info(f"Applying safe dynamic operation for client {client_id}: {operation}")

    try:
        # FIXED SINK: Replaced eval() with a safe mapping of allowed operations.
        # Example payload: {"dataset": [1, 2, 3], "operation": {"type": "multiply", "value": 2}}
        op_type = operation.get('type')
        op_value = operation.get('value')
        
        if op_type in ['multiply', 'add', 'power'] and not isinstance(op_value, (int, float)):
            return jsonify({'error': 'Operation value must be numeric for this operation type.'}), 400

        # Safely apply the requested transformation using native Python operators
        if op_type == 'multiply':
            result = [x * op_value for x in dataset]
        elif op_type == 'add':
            result = [x + op_value for x in dataset]
        elif op_type == 'power':
            result = [x ** op_value for x in dataset]
        elif op_type == 'filter_greater_than':
            result = [x for x in dataset if x > op_value]
        else:
            return jsonify({'error': f'Unsupported operation type: {op_type}'}), 400
        
        return jsonify({
            'status': 'success',
            'dataset_size': len(dataset),
            'computed_result': result
        })
    except Exception as e:
        SYSTEM_DB['metrics']['failed_requests'] += 1
        logger.error(f"Dynamic processing encountered an error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to process dataset with the requested operation.'
        }), 500

if __name__ == '__main__':
    logger.info("Initializing Advanced Data Processor API on port 8080...")
    # App runs globally accessible, increasing risk profile of the vulnerable endpoint
    app.run(host='0.0.0.0', port=8080, threaded=True)
