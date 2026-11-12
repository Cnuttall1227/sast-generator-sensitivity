import os
import io
import json
from datetime import datetime

import pandas as pd
import streamlit as st

REPORTS_ROOT = os.environ.get("REPORTS_ROOT", "/srv/reports")
CATALOG_FILE = os.path.join(REPORTS_ROOT, "catalog.json")
MAX_ROWS_PREVIEW = 500
MAX_FILE_BYTES = 50 * 1024 * 1024

st.set_page_config(page_title="Report viewer", layout="wide")


@st.cache_data(ttl=60)
def load_catalog():
    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"reports": []}


def catalog_options(catalog):
    return {entry["title"]: entry["file"] for entry in catalog.get("reports", [])}


def load_report(relative_file):
    report_path = os.path.join(REPORTS_ROOT, relative_file)
    if not os.path.isfile(report_path):
        raise FileNotFoundError(relative_file)
    if os.path.getsize(report_path) > MAX_FILE_BYTES:
        raise ValueError("Report is too large to display")
    with open(report_path, "rb") as handle:
        raw = handle.read()
    if report_path.lower().endswith(".json"):
        frame = pd.read_json(io.BytesIO(raw))
    else:
        frame = pd.read_csv(io.BytesIO(raw))
    modified = datetime.fromtimestamp(os.path.getmtime(report_path))
    return frame, raw, modified


def numeric_summary(frame):
    numeric = frame.select_dtypes("number")
    if numeric.empty:
        return None
    return numeric.describe().transpose()


def render_report(relative_file):
    try:
        frame, raw, modified = load_report(relative_file)
    except FileNotFoundError:
        st.error(f"Report not found: {relative_file}")
        return
    except ValueError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.error(f"Could not parse report: {exc}")
        return
    st.caption(f"{relative_file} · {len(frame):,} rows · updated {modified:%Y-%m-%d %H:%M}")
    tab_data, tab_summary = st.tabs(["Data", "Summary"])
    with tab_data:
        st.dataframe(frame.head(MAX_ROWS_PREVIEW), use_container_width=True)
        if len(frame) > MAX_ROWS_PREVIEW:
            st.info(f"Showing the first {MAX_ROWS_PREVIEW} rows.")
    with tab_summary:
        summary = numeric_summary(frame)
        if summary is None:
            st.write("No numeric columns to summarise.")
        else:
            st.dataframe(summary, use_container_width=True)
    st.download_button(
        "Download original",
        data=raw,
        file_name=os.path.basename(relative_file),
        mime="application/octet-stream",
    )


def main():
    st.title("Report viewer")
    catalog = load_catalog()
    options = catalog_options(catalog)
    linked_file = st.query_params.get("report")

    with st.sidebar:
        st.header("Reports")
        if not options:
            st.write("No reports have been published yet.")
        titles = list(options)
        default_index = 0
        if linked_file in options.values():
            default_index = list(options.values()).index(linked_file)
        choice = st.selectbox("Choose a report", titles, index=default_index) if titles else None
        if st.button("Refresh catalog"):
            load_catalog.clear()
            st.rerun()

    selected_file = linked_file or (options.get(choice) if choice else None)
    if not selected_file:
        st.write("Select a report from the sidebar.")
        return
    if choice and options.get(choice) != linked_file and linked_file is None:
        st.query_params["report"] = selected_file
    st.subheader(next((t for t, f in options.items() if f == selected_file), selected_file))
    st.write(f"Shareable link: `?report={selected_file}`")
    render_report(selected_file)


main()