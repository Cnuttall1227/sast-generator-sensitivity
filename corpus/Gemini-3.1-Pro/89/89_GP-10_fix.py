import http.server
import socketserver
import sqlite3
import os
import xml.etree.ElementTree as ET
import logging
from datetime import datetime

# Configure logging for the B2B Gateway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("B2B_XML_Gateway")

DB_FILE = "b2b_operations.db"
PORT = 8080

def initialize_database():
    """Initializes the SQLite database with merchant accounts and product catalogs."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create merchants table
    cursor.execute('''
        CREATE TABLE merchants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id TEXT UNIQUE NOT NULL,
            company_name TEXT NOT NULL,
            status TEXT NOT NULL,
            credit_limit REAL NOT NULL,
            contact_email TEXT
        )
    ''')
    
    # Create order ledger
    cursor.execute('''
        CREATE TABLE order_ledger (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id TEXT,
            product_code TEXT,
            quantity INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Insert sample merchants
    sample_merchants = [
        ('MCH-1001', 'Acme Corp', 'ACTIVE', 50000.00, 'billing@acmecorp.local'),
        ('MCH-1002', 'Globex', 'SUSPENDED', 0.00, 'finance@globex.local'),
        ('MCH-1003', 'Soylent', 'ACTIVE', 150000.00, 'orders@soylent.local'),
        ('MCH-9999', 'Admin Systems', 'INTERNAL', 9999999.00, 'sysadmin@b2b.local')
    ]
    
    cursor.executemany('''
        INSERT INTO merchants (merchant_id, company_name, status, credit_limit, contact_email)
        VALUES (?, ?, ?, ?, ?)
    ''', sample_merchants)
    
    conn.commit()
    conn.close()
    logger.info("B2B Database initialized with merchant reference data.")

def record_order(merchant_id, product_code, quantity):
    """Securely logs an incoming order to the ledger using parameterized queries."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO order_ledger (merchant_id, product_code, quantity)
            VALUES (?, ?, ?)
        ''', (merchant_id, product_code, quantity))
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"Failed to record order: {e}")
        return False
    finally:
        conn.close()

def verify_merchant_authorization(merchant_id):
    """
    SECURE: Uses parameterized queries (?) to prevent SQL Injection
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Secure parameterized query
    query = "SELECT company_name, status, credit_limit FROM merchants WHERE merchant_id = ?"
    
    try:
        logger.info(f"Checking authorization with secure query for merchant: {merchant_id}")
        # The XML data is passed safely as a tuple parameter
        cursor.execute(query, (merchant_id,))
        record = cursor.fetchone()
        
        if record:
            return {
                "authorized": record[1] in ["ACTIVE", "INTERNAL"],
                "company_name": record[0],
                "status": record[1],
                "credit_limit": record[2]
            }
        return {"authorized": False, "error": "Merchant not found"}
        
    except sqlite3.Error as e:
        logger.error(f"Database error during authorization check: {e}")
        # Generic error message prevents error-based data leakage
        return {"authorized": False, "error": "A database error occurred."}
    finally:
        conn.close()

class B2BXMLRequestHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        """Handles incoming POST requests containing XML order payloads."""
        content_length = int(self.headers.get('Content-Length', 0))
        
        if content_length == 0:
            self.send_error_response(400, "Empty request body")
            return
            
        post_data = self.rfile.read(content_length).decode('utf-8')
        logger.info("Received POST request. Parsing XML payload...")
        
        try:
            # Parse the incoming XML string
            root = ET.fromstring(post_data)
            
            # Extract data from XML nodes
            merchant_node = root.find('merchant_id')
            product_node = root.find('order/product_code')
            quantity_node = root.find('order/quantity')
            
            if merchant_node is None or product_node is None or quantity_node is None:
                self.send_error_response(400, "Missing required XML nodes")
                return
                
            merchant_id = merchant_node.text
            product_code = product_node.text
            try:
                quantity = int(quantity_node.text)
            except ValueError:
                self.send_error_response(400, "Invalid quantity format")
                return
                
            # Triggering the vulnerable function using data extracted from the XML
            auth_result = verify_merchant_authorization(merchant_id)
            
            if not auth_result.get("authorized"):
                error_msg = auth_result.get("error", "Unauthorized merchant status")
                self.send_error_response(403, f"Authorization failed: {error_msg}")
                return
                
            # Process the order securely if authorized
            if record_order(merchant_id, product_code, quantity):
                self.send_success_response(auth_result["company_name"], product_code)
            else:
                self.send_error_response(500, "Internal ledger error")
                
        except ET.ParseError:
            self.send_error_response(400, "Malformed XML payload")
            
    def send_error_response(self, status_code, message):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/xml')
        self.end_headers()
        response_xml = f"<?xml version='1.0'?><response><status>ERROR</status><message>{message}</message></response>"
        self.wfile.write(response_xml.encode('utf-8'))
        
    def send_success_response(self, company, product):
        self.send_response(200)
        self.send_header('Content-type', 'application/xml')
        self.end_headers()
        response_xml = f"<?xml version='1.0'?><response><status>SUCCESS</status><message>Order for {product} accepted for {company}</message></response>"
        self.wfile.write(response_xml.encode('utf-8'))

def run_server():
    initialize_database()
    
    with socketserver.TCPServer(("", PORT), B2BXMLRequestHandler) as httpd:
        logger.info(f"B2B XML Gateway listening on port {PORT}...")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down gateway.")
            httpd.server_close()

if __name__ == "__main__":
    # Example Malicious XML Payload to send via POST request:
    # <?xml version="1.0"?>
    # <b2b_request>
    #     <merchant_id>MCH-1001' UNION SELECT contact_email, 'ACTIVE', 999 FROM merchants WHERE merchant_id='MCH-9999'--</merchant_id>
    #     <order>
    #         <product_code>WIDGET-X</product_code>
    #         <quantity>10</quantity>
    #     </order>
    # </b2b_request>
    
    run_server()
