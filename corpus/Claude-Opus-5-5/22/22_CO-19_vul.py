import os
import io
import base64
import logging
from datetime import datetime

import pandas as pd
from dash import Dash, Input, Output, State, dash_table, dcc, html, no_update

DATASET_DIR = os.environ.get("DATASET_DIR", "/srv/sensor-datasets")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
REQUIRED_COLUMNS = {"timestamp", "sensor", "value"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sensor-dash")

app = Dash(__name__, title="Sensor datasets")
server = app.server


def stored_datasets():
    os.makedirs(DATASET_DIR, exist_ok=True)
    return sorted(name for name in os.listdir(DATASET_DIR) if name.endswith(".csv"))


def decode_upload(contents):
    header, encoded = contents.split(",", 1)
    if "csv" not in header and "text" not in header and "excel" not in header:
        raise ValueError("Please upload a CSV file")
    data = base64.b64decode(encoded)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("File is larger than 10 MB")
    return data


def save_dataset(filename, data):
    frame = pd.read_csv(io.BytesIO(data))
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")
    if not filename.lower().endswith(".csv"):
        filename += ".csv"
    destination = os.path.join(DATASET_DIR, filename)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "wb") as handle:
        handle.write(data)
    log.info("Stored dataset %s (%d rows)", filename, len(frame))
    return filename, len(frame)


def load_dataset(name):
    if name not in stored_datasets():
        raise ValueError("Unknown dataset")
    frame = pd.read_csv(os.path.join(DATASET_DIR, name), parse_dates=["timestamp"])
    return frame.sort_values("timestamp")


app.layout = html.Div([
    html.H1("Sensor datasets"),
    dcc.Upload(
        id="upload",
        children=html.Div(["Drag a CSV here or ", html.A("choose a file")]),
        style={"border": "2px dashed #999", "padding": "1.5rem", "textAlign": "center"},
        multiple=False,
    ),
    html.Div(id="upload-status", style={"margin": "0.75rem 0"}),
    dcc.Dropdown(id="dataset", options=stored_datasets(), placeholder="Choose a dataset"),
    dcc.Dropdown(id="sensor", placeholder="Filter by sensor", multi=True),
    dcc.Graph(id="chart"),
    dash_table.DataTable(id="summary", page_size=10, style_table={"overflowX": "auto"}),
])


@app.callback(
    Output("upload-status", "children"),
    Output("dataset", "options"),
    Output("dataset", "value"),
    Input("upload", "contents"),
    State("upload", "filename"),
    prevent_initial_call=True,
)
def handle_upload(contents, filename):
    if contents is None or not filename:
        return no_update, no_update, no_update
    try:
        data = decode_upload(contents)
        stored, rows = save_dataset(filename, data)
    except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        return f"Upload failed: {exc}", no_update, no_update
    message = f"Saved {stored} with {rows:,} rows at {datetime.now():%H:%M:%S}"
    return message, stored_datasets(), stored


@app.callback(
    Output("sensor", "options"),
    Output("chart", "figure"),
    Output("summary", "data"),
    Input("dataset", "value"),
    Input("sensor", "value"),
)
def show_dataset(name, sensors):
    if not name:
        return [], {"data": [], "layout": {"title": "No dataset selected"}}, []
    try:
        frame = load_dataset(name)
    except (ValueError, FileNotFoundError):
        return [], {"data": [], "layout": {"title": "Dataset not available"}}, []
    sensor_options = sorted(frame["sensor"].astype(str).unique())
    if sensors:
        frame = frame[frame["sensor"].astype(str).isin(sensors)]
    traces = [
        {"x": group["timestamp"], "y": group["value"], "type": "scatter", "mode": "lines", "name": sensor}
        for sensor, group in frame.groupby("sensor")
    ]
    summary = (
        frame.groupby("sensor")["value"]
        .agg(["count", "min", "mean", "max"])
        .round(3)
        .reset_index()
        .to_dict("records")
    )
    figure = {"data": traces, "layout": {"title": name, "xaxis": {"title": "Time"}, "yaxis": {"title": "Value"}}}
    return sensor_options, figure, summary


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8050")))