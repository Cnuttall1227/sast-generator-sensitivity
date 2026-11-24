import logging
import sys
from datetime import datetime
from aiohttp import web

# Configure logging for the E-commerce Microservice
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("Storefront-Catalog-Service")

# In-memory mock database of products for the e-commerce store
PRODUCT_CATALOG = [
    {"id": "p101", "name": "Wireless Noise-Canceling Headphones", "price": 299.99, "category": "electronics", "stock": 45},
    {"id": "p102", "name": "Mechanical Gaming Keyboard", "price": 149.50, "category": "electronics", "stock": 12},
    {"id": "p103", "name": "Ergonomic Office Chair", "price": 199.00, "category": "furniture", "stock": 8},
    {"id": "p104", "name": "Adjustable Standing Desk", "price": 450.00, "category": "furniture", "stock": 3},
    {"id": "p105", "name": "Stainless Steel Water Bottle", "price": 24.99, "category": "accessories", "stock": 120},
    {"id": "p106", "name": "Blue Light Blocking Glasses", "price": 35.00, "category": "accessories", "stock": 85},
]

async def index_handler(request: web.Request) -> web.Response:
    """Handles requests to the storefront homepage."""
    logger.info(f"Homepage accessed by {request.remote}")
    
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>NextGen Tech & Office Store</title>
        <style>
            body { font-family: 'Open Sans', Arial, sans-serif; background-color: #fafafa; color: #333; margin: 0; padding: 0; }
            header { background-color: #2c3e50; color: #fff; padding: 20px 40px; text-align: center; }
            .container { max-width: 900px; margin: 40px auto; padding: 20px; background: #fff; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
            .categories { display: flex; justify-content: center; gap: 20px; margin-top: 20px; }
            .category-link { padding: 15px 30px; background-color: #3498db; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; transition: background 0.3s; }
            .category-link:hover { background-color: #2980b9; }
        </style>
    </head>
    <body>
        <header>
            <h1>NextGen Tech & Office Store</h1>
            <p>Your one-stop shop for modern workspace essentials.</p>
        </header>
        <div class="container">
            <h2 style="text-align: center;">Browse by Category</h2>
            <div class="categories">
                <a href="/category/electronics" class="category-link">Electronics</a>
                <a href="/category/furniture" class="category-link">Furniture</a>
                <a href="/category/accessories" class="category-link">Accessories</a>
            </div>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html_content, content_type='text/html')


async def category_handler(request: web.Request) -> web.Response:
    """
    VULNERABLE FUNCTION: CWE-79 Cross-Site Scripting (XSS)
    Context: Reflected XSS via URL Path Parameter (Route Variable).
    
    This handler extracts the 'category_name' from the URL path pattern 
    (/category/{category_name}). It directly reflects this unsanitized path 
    variable into the HTML DOM.
    
    Trigger Path:
    An attacker creates a malicious link where the category name contains a script:
    http://target.local:8080/category/<script>alert(document.cookie)</script>
    
    Because the aiohttp router matches the path segment and extracts it exactly as 
    provided, and because the handler formats it into the HTML string without 
    using `html.escape()` or a safe templating engine (like Jinja2), the script 
    executes when the victim's browser renders the resulting 404 or category page.
    """
    # Extract the unvalidated category name from the URL path
    category_name = request.match_info.get('category_name', 'Unknown')
    
    logger.info(f"User requested category view for: {category_name}")
    
    # Filter the mock database for products matching the requested category
    matching_products = [p for p in PRODUCT_CATALOG if p['category'].lower() == category_name.lower()]

    # VULNERABLE SINK: The category_name variable is concatenated directly into 
    # the HTML response. It appears both in the document title and the h2 heading.
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <!-- XSS Injection Point 1: Inside the title tag -->
        <title>Category: {category_name} - NextGen Store</title>
        <style>
            body {{ font-family: 'Open Sans', Arial, sans-serif; background-color: #fafafa; color: #333; margin: 0; padding: 0; }}
            header {{ background-color: #2c3e50; color: #fff; padding: 20px 40px; text-align: center; }}
            .container {{ max-width: 900px; margin: 40px auto; padding: 20px; background: #fff; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            .product-card {{ border: 1px solid #eee; padding: 15px; margin-bottom: 15px; border-radius: 5px; display: flex; justify-content: space-between; align-items: center; }}
            .product-info h3 {{ margin: 0 0 5px 0; color: #2c3e50; }}
            .product-price {{ font-size: 1.2em; color: #27ae60; font-weight: bold; }}
            .back-btn {{ display: inline-block; margin-top: 20px; color: #3498db; text-decoration: none; }}
        </style>
    </head>
    <body>
        <header>
            <h1>NextGen Tech & Office Store</h1>
        </header>
        <div class="container">
            <!-- XSS Injection Point 2: Inside an HTML heading -->
            <h2>Browsing Category: <span style="color: #e67e22;">{category_name}</span></h2>
            
            <p>Found {len(matching_products)} products in this category.</p>
    """
    
    if matching_products:
        for product in matching_products:
            html_content += f"""
            <div class="product-card">
                <div class="product-info">
                    <h3>{product['name']}</h3>
                    <small>Stock: {product['stock']} units available</small>
                </div>
                <div class="product-price">${product['price']:.2f}</div>
            </div>
            """
    else:
        html_content += """
            <div style="background-color: #fce4e4; color: #c0392b; padding: 15px; border-radius: 5px;">
                <strong>Notice:</strong> No products were found in this category. It may have been discontinued or the URL is incorrect.
            </div>
        """

    html_content += """
            <a href="/" class="back-btn">&larr; Return to Homepage</a>
        </div>
    </body>
    </html>
    """
    
    # If no products were found, we could return a 404, but we still render the vulnerable HTML
    status_code = 200 if matching_products else 404
    return web.Response(text=html_content, content_type='text/html', status=status_code)


def init_app() -> web.Application:
    """Initializes the aiohttp web application and sets up routing."""
    app = web.Application()
    
    # Define application routes
    app.router.add_get('/', index_handler)
    # The {category_name} parameter captures the path segment dynamically
    app.router.add_get('/category/{category_name}', category_handler)
    
    return app


if __name__ == '__main__':
    port = 8080
    logger.info(f"Starting aiohttp Storefront Service on port {port}...")
    try:
        # Run the asynchronous web server
        web.run_app(init_app(), port=port, print=None)
    except KeyboardInterrupt:
        logger.info("Application terminated by user.")
        sys.exit(0)
