import io
import os
import json
import logging
from datetime import datetime, timezone

import pandas as pd
from sanic import Sanic, response
from sanic.exceptions import BadRequest, Unauthorized

API_KEYS = set(filter(None, os.environ.get("BUDGET_API_KEYS", "").split(",")))
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
REQUIRED_COLUMNS = {"date", "category", "amount"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("budget-insights")

app = Sanic("budget_insights")


def require_key(request):
    if not API_KEYS or request.headers.get("x-api-key", "") not in API_KEYS:
        raise Unauthorized("API key required")


def read_snapshot(upload):
    name = (upload.name or "").lower()
    body = upload.body
    if name.endswith(".csv"):
        frame = pd.read_csv(io.BytesIO(body))
    elif name.endswith(".parquet"):
        frame = pd.read_parquet(io.BytesIO(body), engine="pyarrow")
    elif name.endswith((".pkl", ".pickle")):
        raise ValueError("pickle snapshots are no longer accepted; export a .parquet or .csv file instead")
    else:
        raise ValueError("upload a .csv export or a .parquet snapshot saved from the desktop app")
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("the snapshot doesn't contain a table")
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {', '.join(sorted(missing))}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    return frame.dropna(subset=["date", "amount"])


def monthly_summary(frame):
    spending = frame[frame["amount"] < 0].copy()
    spending["month"] = spending["date"].dt.to_period("M").astype(str)
    by_month = spending.groupby("month")["amount"].sum().abs().round(2)
    by_category = spending.groupby("category")["amount"].sum().abs().sort_values(ascending=False).round(2)
    income = frame[frame["amount"] > 0]["amount"].sum()
    return {
        "months": by_month.to_dict(),
        "top_categories": by_category.head(8).to_dict(),
        "total_income": round(float(income), 2),
        "total_spending": round(float(spending["amount"].abs().sum()), 2),
    }


def unusual_transactions(frame):
    spending = frame[frame["amount"] < 0]
    flagged = []
    for category, group in spending.groupby("category"):
        if len(group) < 5:
            continue
        typical = group["amount"].abs().median()
        for _, row in group[group["amount"].abs() > typical * 3].iterrows():
            flagged.append({"date": row["date"].date().isoformat(), "category": category,
                            "amount": round(abs(float(row["amount"])), 2), "typical": round(float(typical), 2)})
    return sorted(flagged, key=lambda f: f["amount"], reverse=True)[:15]


@app.post("/insights")
async def insights(request):
    require_key(request)
    upload = request.files.get("snapshot")
    if upload is None:
        raise BadRequest("send the file in a 'snapshot' form field")
    if len(upload.body) > MAX_UPLOAD_BYTES:
        raise BadRequest("file larger than 20 MB")
    try:
        frame = read_snapshot(upload)
    except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise BadRequest(f"could not read the file: {exc}")
    if frame.empty:
        raise BadRequest("no usable transactions in the file")
    result = {
        "transactions": int(len(frame)),
        "period": {"from": frame["date"].min().date().isoformat(), "to": frame["date"].max().date().isoformat()},
        "summary": monthly_summary(frame),
        "unusual": unusual_transactions(frame),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    log.info("Built insights for %d transaction(s)", result["transactions"])
    return response.json(json.loads(json.dumps(result, default=str)))


@app.get("/health")
async def health(request):
    return response.json({"status": "ok", "pandas": pd.__version__})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), single_process=True)