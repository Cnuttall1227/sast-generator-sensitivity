import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("SALES_DATABASE_URL", "postgresql+psycopg2://reporting:reporting@localhost/sales")
REGIONS = ["All", "North", "South", "East", "West"]

st.set_page_config(page_title="Sales explorer", layout="wide")


@st.cache_resource
def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True)


@st.cache_data(ttl=300)
def load_reps():
    with get_engine().connect() as conn:
        return pd.read_sql(text("SELECT id, full_name FROM sales_reps WHERE active ORDER BY full_name"), conn)


def load_orders(start, end, region, customer_text):
    conditions = ["o.ordered_on BETWEEN :start AND :end"]
    params = {"start": start, "end": end}
    if region != "All":
        conditions.append("c.region = :region")
        params["region"] = region
    if customer_text:
        conditions.append(f"c.name ILIKE '%{customer_text}%'")
    query = text(
        "SELECT o.ordered_on, c.name AS customer, c.region, r.full_name AS rep, "
        "o.order_number, o.total "
        "FROM orders o JOIN customers c ON c.id = o.customer_id "
        "JOIN sales_reps r ON r.id = o.rep_id "
        f"WHERE {' AND '.join(conditions)} "
        "ORDER BY o.ordered_on DESC LIMIT 5000"
    )
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params=params)


def summarize(frame):
    if frame.empty:
        return frame
    daily = frame.groupby("ordered_on", as_index=False)["total"].sum()
    daily["ordered_on"] = pd.to_datetime(daily["ordered_on"])
    return daily.set_index("ordered_on")


def main():
    st.title("Sales explorer")
    with st.sidebar:
        st.header("Filters")
        default_start = date.today() - timedelta(days=30)
        start, end = st.date_input("Order dates", value=(default_start, date.today()))
        region = st.selectbox("Region", REGIONS)
        customer_text = st.text_input("Customer name contains", max_chars=60).strip()
        reps = load_reps()
        rep_names = st.multiselect("Sales reps", options=reps["full_name"].tolist())

    if start > end:
        st.error("The start date must be before the end date.")
        return

    try:
        orders = load_orders(start, end, region, customer_text)
    except Exception as exc:
        st.error(f"Could not load orders: {type(exc).__name__}")
        return

    if rep_names:
        orders = orders[orders["rep"].isin(rep_names)]

    total_revenue = float(orders["total"].sum()) if not orders.empty else 0.0
    col1, col2, col3 = st.columns(3)
    col1.metric("Orders", f"{len(orders):,}")
    col2.metric("Revenue", f"${total_revenue:,.2f}")
    col3.metric("Customers", f"{orders['customer'].nunique():,}" if not orders.empty else "0")

    daily = summarize(orders)
    if not daily.empty:
        st.subheader("Revenue by day")
        st.line_chart(daily["total"])

    st.subheader("Orders")
    st.dataframe(orders, use_container_width=True, hide_index=True)
    if not orders.empty:
        st.download_button(
            "Download CSV",
            data=orders.to_csv(index=False).encode("utf-8"),
            file_name=f"orders-{start}-{end}.csv",
            mime="text/csv",
        )


main()