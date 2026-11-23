import cherrypy
import logging
import sys
import time
from datetime import datetime

# Configure logging for the Coffee Shop application
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("CafeApp")

# Mock database of coffee shop items
MENU_ITEMS = [
    {"id": 1, "name": "Espresso", "price": "$2.50", "desc": "Strong and bold classic espresso."},
    {"id": 2, "name": "Cappuccino", "price": "$3.75", "desc": "Espresso topped with steamed milk and thick foam."},
    {"id": 3, "name": "Latte", "price": "$4.00", "desc": "Smooth espresso with plenty of steamed milk."},
    {"id": 4, "name": "Mocha", "price": "$4.50", "desc": "Chocolate espresso with steamed milk and whipped cream."},
    {"id": 5, "name": "Cold Brew", "price": "$3.50", "desc": "Slow-steeped cold coffee served over ice."}
]

class CoffeeShop(object):
    @cherrypy.expose
    def index(self):
        """Landing page that redirects to the menu."""
        logger.info("Visitor accessed the homepage.")
        raise cherrypy.HTTPRedirect("/menu")

    @cherrypy.expose
    def set_preference(self, drink=None):
        """Endpoint to set a user's favorite drink preference via a cookie."""
        if drink:
            # Set a cookie that expires in 30 days
            cherrypy.response.cookie['favorite_drink'] = drink
            cherrypy.response.cookie['favorite_drink']['path'] = '/'
            cherrypy.response.cookie['favorite_drink']['max-age'] = 3600 * 24 * 30
            logger.info(f"User preference cookie set to: {drink}")
            
        raise cherrypy.HTTPRedirect("/menu")

    @cherrypy.expose
    def menu(self):
        """
        VULNERABLE FUNCTION: CWE-79 Cross-Site Scripting (XSS)
        Context: Reflected/Stored XSS via HTTP Cookie.
        
        This function reads the 'favorite_drink' cookie from the incoming request
        and directly embeds its value into the HTML response without sanitization
        or HTML entity encoding.
        
        Trigger Path:
        An attacker can craft a malicious URL to the /set_preference endpoint:
        http://target.local:8080/set_preference?drink=<script>alert('XSS')</script>
        When the victim clicks the link, the server sets the malicious payload as 
        the value of the 'favorite_drink' cookie. Upon redirection to the /menu 
        endpoint, the server reads this cookie and reflects the script directly 
        into the DOM, executing it in the victim's browser context.
        """
        logger.info("Visitor accessed the menu page.")
        
        # Extract the cookie value if it exists, otherwise default to 'Coffee'
        favorite_drink = "Coffee"
        if 'favorite_drink' in cherrypy.request.cookie:
            favorite_drink = cherrypy.request.cookie['favorite_drink'].value
            
        # VULNERABLE SINK: The 'favorite_drink' variable (derived from the cookie) 
        # is concatenated directly into the HTML string.
        html_response = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Artisan Coffee Shop</title>
            <style>
                body {{ font-family: 'Georgia', serif; background-color: #fdf8f5; color: #4a3b32; margin: 0; padding: 0; }}
                header {{ background-color: #3e2723; color: #fff; padding: 20px; text-align: center; }}
                h1 {{ margin: 0; font-size: 2.5em; letter-spacing: 2px; }}
                .container {{ max-width: 800px; margin: 30px auto; padding: 0 20px; }}
                .welcome-banner {{ background-color: #d7ccc8; padding: 15px; border-radius: 5px; text-align: center; margin-bottom: 30px; border-left: 5px solid #8d6e63; }}
                .menu-item {{ background: #fff; border: 1px solid #e0e0e0; margin-bottom: 15px; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
                .menu-item h3 {{ margin-top: 0; color: #5d4037; display: flex; justify-content: space-between; }}
                .price {{ color: #e64a19; font-weight: bold; }}
                .pref-form {{ background: #efebe9; padding: 20px; border-radius: 8px; margin-top: 40px; text-align: center; }}
                input[type="text"] {{ padding: 10px; width: 60%; border: 1px solid #bcaaa4; border-radius: 4px; }}
                button {{ background-color: #5d4037; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-size: 1em; }}
                button:hover {{ background-color: #3e2723; }}
            </style>
        </head>
        <body>
            <header>
                <h1>Artisan Coffee Roasters</h1>
            </header>
            
            <div class="container">
                <!-- Injection Point: Unescaped cookie value reflected here -->
                <div class="welcome-banner">
                    <h2>Welcome back! Enjoy your favorite: <span style="color: #bf360c;">{favorite_drink}</span></h2>
                </div>
                
                <h2>Today's Menu</h2>
        """
        
        for item in MENU_ITEMS:
            html_response += f"""
                <div class="menu-item">
                    <h3>{item['name']} <span class="price">{item['price']}</span></h3>
                    <p>{item['desc']}</p>
                </div>
            """
            
        html_response += """
                <div class="pref-form">
                    <h3>Update Your Favorite Drink</h3>
                    <form action="/set_preference" method="GET">
                        <input type="text" name="drink" placeholder="E.g., Iced Caramel Macchiato" required>
                        <button type="submit">Save Preference</button>
                    </form>
                </div>
            </div>
        </body>
        </html>
        """
        return html_response

if __name__ == '__main__':
    port = 8080
    logger.info(f"Starting CherryPy Coffee Shop App on port {port}...")
    
    # Configure the CherryPy server
    cherrypy.config.update({
        'server.socket_host': '0.0.0.0',
        'server.socket_port': port,
        'environment': 'production'
    })
    
    # Start the application
    cherrypy.quickstart(CoffeeShop())
