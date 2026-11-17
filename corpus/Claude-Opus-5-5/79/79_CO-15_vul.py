import io
import base64
import logging
from datetime import datetime

import pandas as pd
from dash import Dash, Input, Output, State, dcc, html, no_update

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
REQUIRED_COLUMNS = ["volunteer", "hours", "team"]
REPORT_TITLE = "Monthly volunteer hours"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hours-report")

app = Dash(__name__, title="Volunteer hours")
server = app.server

REPORT_STYLE = """
body { font-family: Georgia, serif; margin: 2rem; color: #222; }
h1 { border-bottom: 2px solid #444; padding-bottom: .25rem; }
table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
th, td { border-bottom: 1px solid #ccc; padding: .35rem .5rem; text-align: left; }
td.num { text-align: right; }
.team { margin-top: 2rem; }
"""


def parse_upload(contents):
    _, encoded = contents.split(",", 1)
    data = base64.b64decode(encoded)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("File is larger than 5 MB")
    frame = pd.read_csv(io.BytesIO(data))
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")
    frame["hours"] = pd.to_numeric(frame["hours"], errors="coerce").fillna(0)
    frame["volunteer"] = frame["volunteer"].astype(str).str.strip()
    frame["team"] = frame["team"].astype(str).str.strip()
    return frame[frame["volunteer"] != ""]


def build_report_html(frame, month_label):
    sections = []
    for team, group in frame.groupby("team"):
        totals = group.groupby("volunteer")["hours"].sum().sort_values(ascending=False)
        rows = "".join(
            f"<tr><td>{volunteer}</td><td class='num'>{hours:.1f}</td></tr>"
            for volunteer, hours in totals.items()
        )
        sections.append(
            f"<section class='team'><h2>{team}</h2>"
            f"<table><tr><th>Volunteer</th><th>Hours</th></tr>{rows}</table>"
            f"<p>Team total: {totals.sum():.1f} hours</p></section>"
        )
    grand_total = frame["hours"].sum()
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><style>{REPORT_STYLE}</style></head><body>"
        f"<h1>{REPORT_TITLE} – {month_label}</h1>"
        f"<p>{len(frame['volunteer'].unique())} volunteers logged {grand_total:.1f} hours.</p>"
        f"{''.join(sections)}"
        f"<p><small>Generated {datetime.now():%d %b %Y %H:%M}</small></p>"
        f"</body></html>"
    )


app.layout = html.Div(
    style={"maxWidth": "60rem", "margin": "2rem auto", "fontFamily": "sans-serif"},
    children=[
        html.H1("Volunteer hours report"),
        html.P("Upload the timesheet export (CSV with volunteer, hours, team columns)."),
        dcc.Input(id="month", placeholder="Month, e.g. October 2026", style={"width": "16rem"}),
        dcc.Upload(
            id="upload",
            children=html.Div(["Drop the CSV here or ", html.A("choose a file")]),
            style={"border": "2px dashed #999", "padding": "1.25rem", "textAlign": "center", "marginTop": "1rem"},
        ),
        html.Div(id="status", style={"margin": "1rem 0"}),
        html.Button("Print report", id="print", n_clicks=0),
        html.Iframe(id="preview", style={"width": "100%", "height": "36rem", "border": "1px solid #ddd"}),
    ],
)


@app.callback(
    Output("preview", "srcDoc"),
    Output("status", "children"),
    Input("upload", "contents"),
    Input("month", "value"),
    State("upload", "filename"),
    prevent_initial_call=True,
)
def update_preview(contents, month, filename):
    if not contents:
        return no_update, "Upload a timesheet to see the report."
    month_label = (month or datetime.now().strftime("%B %Y")).strip()[:40]
    try:
        frame = parse_upload(contents)
    except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        return no_update, f"Could not read {filename or 'the file'}: {exc}"
    log.info("Built report from %s with %d rows", filename, len(frame))
    return build_report_html(frame, month_label), f"Loaded {len(frame):,} rows from {filename}."


app.clientside_callback(
    """function(n) {
        if (n) { document.getElementById("preview").contentWindow.print(); }
        return "";
    }""",
    Output("print", "title"),
    Input("print", "n_clicks"),
    prevent_initial_call=True,
)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050)