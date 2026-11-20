import sqlite3
import os
import logging
import threading
import xmlrpc.client
from xmlrpc.server import SimpleXMLRPCServer
from xmlrpc.server import SimpleXMLRPCRequestHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("HR_RPC_Service")

DB_FILE = "hr_data.db"

class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/RPC2',)

def initialize_database():
    """Initializes the SQLite database with employee records."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create table
    cursor.execute('''
        CREATE TABLE employees (
            emp_id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            department TEXT NOT NULL,
            salary REAL NOT NULL,
            email TEXT UNIQUE NOT NULL
        )
    ''')
    
    # Insert sample data
    sample_employees = [
        ('John', 'Doe', 'Engineering', 95000.00, 'jdoe@company.local'),
        ('Jane', 'Smith', 'Marketing', 82000.00, 'jsmith@company.local'),
        ('Robert', 'Johnson', 'Engineering', 105000.00, 'rjohnson@company.local'),
        ('Emily', 'Davis', 'Human Resources', 75000.00, 'edavis@company.local'),
        ('Michael', 'Wilson', 'Sales', 89000.00, 'mwilson@company.local'),
        ('Admin', 'System', 'IT', 150000.00, 'admin@company.local')
    ]
    
    cursor.executemany('''
        INSERT INTO employees (first_name, last_name, department, salary, email)
        VALUES (?, ?, ?, ?, ?)
    ''', sample_employees)
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully with sample data.")

def get_employee_details(emp_id):
    """Secure function to get specific employee details."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM employees WHERE emp_id = ?", (emp_id,))
        record = cursor.fetchone()
        return record if record else "Employee not found."
    except sqlite3.Error as e:
        logger.error(f"Database error in get_employee_details: {e}")
        return f"Error: {e}"
    finally:
        conn.close()

def search_employees_by_department(department):
    """
    SECURE: Uses parameterized queries (?) to prevent SQL Injection
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Secure parameterized query
    query = "SELECT first_name, last_name, email FROM employees WHERE department = ?"
    
    try:
        logger.info(f"Executing secure database query for department: {department}")
        cursor.execute(query, (department,))
        records = cursor.fetchall()
        
        result = []
        for row in records:
            result.append({
                'first_name': row[0],
                'last_name': row[1],
                'email': row[2]
            })
        return result
    except sqlite3.Error as e:
        logger.error(f"Database error in search_employees_by_department: {e}")
        return [{"error": str(e)}]
    finally:
        conn.close()
def get_department_statistics():
    """Returns aggregate statistics for departments securely."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT department, COUNT(*), AVG(salary) FROM employees GROUP BY department")
        records = cursor.fetchall()
        return [{"department": r[0], "count": r[1], "avg_salary": r[2]} for r in records]
    except sqlite3.Error as e:
        return [{"error": str(e)}]
    finally:
        conn.close()

def run_server():
    initialize_database()
    server = SimpleXMLRPCServer(("localhost", 9000), requestHandler=RequestHandler, allow_none=True)
    server.register_introspection_functions()
    
    # Register functions to expose via XML-RPC
    server.register_function(get_employee_details, 'get_employee')
    server.register_function(search_employees_by_department, 'search_by_dept')
    server.register_function(get_department_statistics, 'get_dept_stats')
    
    logger.info("XML-RPC HR Service running on port 9000...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutting down.")

if __name__ == "__main__":
    # Running the server in a separate thread for demonstration purposes
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    import time
    time.sleep(1) # Wait for server to start
    
    logger.info("Starting local client test...")
    client = xmlrpc.client.ServerProxy('http://localhost:9000')
    
    # Normal usage
    print("\n--- Normal Request ---")
    try:
        normal_response = client.search_by_dept("Engineering")
        print(f"Engineering Department Employees: {normal_response}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Malicious usage demonstrating the SQL Injection
    print("\n--- Malicious Request (SQL Injection) ---")
    # Attacker injects a UNION SELECT to extract restricted salary data into the email field
    malicious_payload = "Engineering' UNION SELECT first_name, last_name, CAST(salary AS TEXT) FROM employees--"
    try:
        hacked_response = client.search_by_dept(malicious_payload)
        print(f"Extracted Data including salaries: {hacked_response}")
    except Exception as e:
        print(f"Error: {e}")
        
    time.sleep(1)
