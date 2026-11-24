import logging
import sys
from datetime import datetime
from typing import Optional
import uvicorn
from fastapi import FastAPI, Request, Path
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("InvoiceMicroservice")

app = FastAPI(title="Invoice Management API", version="1.0.0")

# --- Mock Database ---
INVOICES = {
    "INV-1001": {"amount": 1500.00, "status": "paid", "due_date": "2023-12-01"},
    "INV-1002": {"amount": 350.50, "status": "pending", "due_date": "2023-12-15"},
    "INV-1003": {"amount": 120.00, "status": "pending", "due_date": "2023-12-20"},
}

class InvoiceItem(BaseModel):
    description: str
    quantity: int
    unit_price: float

# --- API Routes ---
@app.get("/api/health")
async def health_check():
    """Standard JSON health check endpoint."""
    return JSONResponse(content={"status": "online", "timestamp": datetime.now().isoformat()})

@app.get("/api/invoices", response_model=dict)
async def list_invoices():
    """Returns all invoices in JSON format."""
    return {"count": len(INVOICES), "data": INVOICES}

import html

@app.get("/invoice/preview/{customer_name}", response_class=HTMLResponse)
async def preview_invoice_html(
    request: Request,
    customer_name: str = Path(..., description="The name of the customer to generate the invoice for"),
    theme: Optional[str] = "light"
):
    """
    FIXED: CWE-79 Improper Neutralization of Input During Web Page Generation (XSS)
    Context: Reflected XSS via an Unescaped Path Parameter.
    
    The 'customer_name' variable is now HTML-escaped before being concatenated 
    into the HTML response string, neutralizing malicious script payloads.
    """
    logger.info(f"Generating HTML invoice preview for customer: {customer_name}")
    
    # Simulate fetching outstanding balance for the dashboard
    outstanding_balance = sum(
        inv["amount"] for inv in INVOICES.values() if inv["status"] == "pending"
    )
            
    bg_color = "#ffffff" if theme == "light" else "#2c3e50"
    text_color = "#333333" if theme == "light" else "#ecf0f1"
    box_bg = "#ffffff" if theme == "light" else "#34495e"
    
    # FIXED SINK: The path parameter is HTML-escaped to neutralize any injected
    # tags or script payloads before concatenation into the DOM context.
    safe_customer_name = html.escape(customer_name)
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <!-- FIXED: Safely escaped parameter reflected inside the <title> tag -->
        <title>Invoice Preview - {safe_customer_name}</title>
        <style>
            body {{
                font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                background-color: {bg_color};
                color: {text_color};
                padding: 40px;
                line-height: 1.6;
            }}
            .invoice-box {{
                max-width: 800px;
                margin: auto;
                padding: 30px;
                border: 1px solid #eee;
                box-shadow: 0 0 10px rgba(0, 0, 0, 0.15);
                background-color: {box_bg};
                border-radius: 8px;
            }}
            .header {{
                text-align: center;
                border-bottom: 2px solid #3498db;
                padding-bottom: 10px;
                margin-bottom: 20px;
            }}
            .balance {{
                font-size: 1.5em;
                font-weight: bold;
                color: #e74c3c;
            }}
            .footer {{
                margin-top: 40px;
                text-align: center;
                font-size: 0.9em;
                opacity: 0.7;
            }}
        </style>
    </head>
    <body>
        <div class="invoice-box">
            <div class="header">
                <!-- FIXED: Safely escaped parameter reflected inside the <h1> tag -->
                <h1>Invoice Statement for {safe_customer_name}</h1>
                <p>Generated on {datetime.now().strftime("%B %d, %Y")}</p>
            </div>
            
            <div class="content">
                <!-- FIXED: Safely escaped parameter reflected again in the body -->
                <p>Dear <strong>{safe_customer_name}</strong>,</p>
                <p>This is a dynamically generated preview of your current account standing based on recent transactions.</p>
                
                <p>Your total outstanding pending balance is: 
                    <span class="balance">${outstanding_balance:.2f}</span>
                </p>
                
                <p>Please contact billing@company.local if you have any questions regarding these charges.</p>
            </div>
            
            <div class="footer">
                <p>Invoice Preview Microservice v1.0.0 | Internal Use Only</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content, status_code=200)

def start_server():
    """Runs the Uvicorn ASGI server hosting the FastAPI application."""
    logger.info("Starting FastAPI Invoice Microservice on port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

if __name__ == "__main__":
    try:
        start_server()
    except KeyboardInterrupt:
        logger.info("Shutting down Invoice Microservice.")
        sys.exit(0)
