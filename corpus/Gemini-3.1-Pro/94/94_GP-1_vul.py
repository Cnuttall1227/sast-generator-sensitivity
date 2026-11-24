import os
import sqlite3
import logging
import cherrypy
from datetime import datetime

# Configure logging for the E-Commerce Dynamic Pricing Engine
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - PricingEngine - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CherryPyPricing")

DB_FILE = "ecommerce_catalog.db"

def init_catalog_db():
    """Initializes the SQLite database for the product catalog."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE products (
            product_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            base_price REAL NOT NULL,
            stock_level INTEGER NOT NULL
        )
    ''')

    mock_products = [
        ('prod_001', 'Wireless Headphones', 199.99, 50),
        ('prod_002', 'Mechanical Keyboard', 149.50, 120),
        ('prod_003', 'Gaming Mouse', 89.99, 200)
    ]
    cursor.executemany('''
        INSERT INTO products (product_id, name, base_price, stock_level)
        VALUES (?, ?, ?, ?)
    ''', mock_products)

    conn.commit()
    conn.close()
    logger.info("Product catalog database initialized.")

def get_cart_total(cart_items: dict) -> float:
    """Calculates the base total for a given cart."""
    total = 0.0
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        for pid, qty in cart_items.items():
            cursor.execute("SELECT base_price FROM products WHERE product_id = ?", (pid,))
            row = cursor.fetchone()
            if row:
                total += row[0] * qty
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error calculating total: {e}")
    return total

def evaluate_discount_rule(rule_expression: str, cart_total: float) -> float:
    """
    VULNERABLE FUNCTION: CWE-94 Improper Control of Generation of Code ('Code Injection')
    Trigger Path: HTTP POST form data -> evaluated as Python code via eval()
    """
    logger.info(f"Evaluating dynamic discount rule: {rule_expression}")
    
    try:
        # Vulnerability: The pricing engine allows administrators to test complex
        # discount formulas dynamically. It takes a raw string from the HTTP request
        # and executes it using Python's built-in eval() function. 
        # An attacker can bypass the intended math logic by injecting arbitrary Python 
        # code. Even with __builtins__ zeroed out, Python's object introspection 
        # allows breaking out of the sandbox.
        #
        # CWE-94 occurs instantly when the untrusted rule_expression is evaluated.
        
        allowed_context = {
            "cart_total": cart_total,
            "max": max,
            "min": min
        }
        
        # The execution environment is weakly restricted, which does not prevent 
        # built-in exploits or traversing the object tree to achieve RCE.
        discounted_total = eval(rule_expression, {"__builtins__": {}}, allowed_context)
        
        return float(discounted_total)
        
    except Exception as e:
        logger.error(f"Rule evaluation failed: {e}")
        return cart_total

class PricingAdminPanel:
    """CherryPy web application for testing pricing rules."""
    
    @cherrypy.expose
    def index(self):
        """Displays the rule testing dashboard."""
        return """
        <html>
            <head><title>Pricing Rule Tester</title></head>
            <body>
                <h2>Dynamic Discount Rule Tester</h2>
                <form method="post" action="test_rule">
                    <label>Cart Total ($):</label><br>
                    <input type="text" name="cart_total" value="500.00"><br><br>
                    <label>Discount Rule (Python Expression):</label><br>
                    <p><i>Example: cart_total * 0.9 (10% off) or cart_total - 50</i></p>
                    <textarea name="rule_expression" rows="4" cols="50">cart_total * 0.85</textarea><br><br>
                    <input type="submit" value="Test Rule">
                </form>
            </body>
        </html>
        """

    @cherrypy.expose
    def test_rule(self, cart_total, rule_expression):
        """Endpoint that processes the submitted rule."""
        try:
            total_val = float(cart_total)
        except ValueError:
            return "Error: Cart total must be a number."

        # Pass the untrusted string directly to the vulnerable function
        final_price = evaluate_discount_rule(rule_expression, total_val)
        
        return f"""
        <html>
            <body>
                <h2>Test Results</h2>
                <p>Original Total: ${total_val:.2f}</p>
                <p>Rule Applied: <code>{rule_expression}</code></p>
                <p><strong>Final Price: ${final_price:.2f}</strong></p>
                <a href="/">Test Another Rule</a>
            </body>
        </html>
        """

if __name__ == '__main__':
    init_catalog_db()
    
    cherrypy.config.update({
        'server.socket_host': '0.0.0.0',
        'server.socket_port': 8080,
        'log.screen': False
    })
    
    # Example Malicious Trigger:
    # 1. Attacker accesses the admin panel.
    # 2. Submits the form with the following rule_expression to achieve RCE:
    #    [c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings'][0]()._module.__builtins__['__import__']('os').popen('whoami').read()
    
    logger.info("Starting CherryPy Pricing Admin on http://0.0.0.0:8080")
    cherrypy.quickstart(PricingAdminPanel())
