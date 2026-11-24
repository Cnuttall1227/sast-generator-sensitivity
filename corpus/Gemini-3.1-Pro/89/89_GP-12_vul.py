from xmlrpc.server import SimpleXMLRPCServer
from xmlrpc.server import SimpleXMLRPCRequestHandler
import sqlite3
import os
import logging
from datetime import datetime

# Configure logging for the Legacy XML-RPC Service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("EnterprisePayroll_XMLRPC")

DB_FILE = "enterprise_payroll.db"
PORT = 9000

def initialize_database():
    """Initializes the SQLite database with employee and sensitive payroll data."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Public employee directory table
    cursor.execute('''
        CREATE TABLE employees (
            emp_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            department TEXT NOT NULL,
            title TEXT NOT NULL
        )
    ''')
    
    # Highly sensitive payroll data table
    cursor.execute('''
        CREATE TABLE payroll_records (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            annual_salary INTEGER NOT NULL,
            bonus_target INTEGER NOT NULL,
            direct_deposit_routing TEXT NOT NULL,
            direct_deposit_account TEXT NOT NULL,
            FOREIGN KEY(username) REFERENCES employees(username)
        )
    ''')
    
    # Insert public employee records
    employees = [
        ('jdoe', 'John Doe', 'Engineering', 'Senior Developer'),
        ('asmith', 'Alice Smith', 'HR', 'HR Manager'),
        ('bwayne', 'Bruce Wayne', 'Executive', 'CEO'),
        ('ckent', 'Clark Kent', 'Media', 'Writer')
    ]
    cursor.executemany('''
        INSERT INTO employees (username, full_name, department, title)
        VALUES (?, ?, ?, ?)
    ''', employees)
    
    # Insert sensitive payroll records
    payroll = [
        ('jdoe', 125000, 15000, '021000021', '123456789'),
        ('asmith', 95000, 5000, '021000021', '987654321'),
        ('bwayne', 1000000, 5000000, '122000661', '555555555'),
        ('ckent', 65000, 2000, '021000021', '111222333')
    ]
    cursor.executemany('''
        INSERT INTO payroll_records (username, annual_salary, bonus_target, direct_deposit_routing, direct_deposit_account)
        VALUES (?, ?, ?, ?, ?)
    ''', payroll)
    
    conn.commit()
    conn.close()
    logger.info("Enterprise database initialized with HR and Payroll mock data.")

class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/RPC2',)

def get_public_directory(department: str):
    """Securely fetches public employee information using parameterized queries."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT full_name, title FROM employees 
            WHERE department = ?
        ''', (department,))
        results = cursor.fetchall()
        return [{"name": row[0], "title": row[1]} for row in results]
    except sqlite3.Error as e:
        logger.error(f"Database error in get_public_directory: {e}")
        return []
    finally:
        conn.close()

def fetch_payroll_data(username: str):
    """
    VULNERABLE FUNCTION: CWE-89 SQL Injection
    Trigger Path: XML-RPC method parameter parsing
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Vulnerability: Direct string concatenation of the XML-RPC argument into the SQL query
    query = f"SELECT annual_salary, bonus_target FROM payroll_records WHERE username = '{username}'"
    
    try:
        logger.info(f"Executing XML-RPC payroll query: {query}")
        cursor.execute(query)
        record = cursor.fetchone()
        
        if not record:
            return {"status": "error", "message": "Payroll record not found."}
            
        return {
            "status": "success",
            "annual_salary": record[0],
            "bonus_target": record[1]
        }
    except sqlite3.Error as e:
        logger.error(f"Database error in fetch_payroll_data: {e}")
        # Leaking the database error back through the XML-RPC response allows error-based injection
        return {"status": "error", "message": f"Database execution failed: {e}"}
    finally:
        conn.close()

def system_ping():
    """Basic health check function for the XML-RPC server."""
    return f"PONG. Server time: {datetime.now().isoformat()}"

def run_server():
    initialize_database()
    
    # Create and configure the XML-RPC server
    server = SimpleXMLRPCServer(("localhost", PORT), requestHandler=RequestHandler, allow_none=True)
    server.register_introspection_functions()
    
    # Register the available XML-RPC procedures
    server.register_function(system_ping, 'system.ping')
    server.register_function(get_public_directory, 'hr.get_public_directory')
    server.register_function(fetch_payroll_data, 'payroll.fetch_payroll_data')
    
    logger.info(f"Legacy XML-RPC Payroll Server listening on port {PORT}...")
    logger.info("Registered methods: system.ping, hr.get_public_directory, payroll.fetch_payroll_data")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down XML-RPC server.")
    finally:
        server.server_close()

if __name__ == "__main__":
    # Example Malicious Python XML-RPC Client code to exploit this:
    # import xmlrpc.client
    # client = xmlrpc.client.ServerProxy("http://localhost:9000/RPC2")
    # exploit_payload = "jdoe' UNION SELECT direct_deposit_routing, direct_deposit_account FROM payroll_records WHERE username='bwayne'--"
    # print(client.payroll.fetch_payroll_data(exploit_payload))
    
    run_server()
