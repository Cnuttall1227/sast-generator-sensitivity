import os
import sys
import uuid
import sqlite3
import logging
import dill
import redis
from datetime import datetime
from celery import Celery

# Configure logging for the Distributed Report Generation Worker
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - ReportWorker - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CeleryReportService")

DB_FILE = "report_jobs.db"
REDIS_URL = "redis://localhost:6379/0"

app = Celery('report_tasks', broker=REDIS_URL, backend=REDIS_URL)
redis_client = redis.Redis.from_url(REDIS_URL)

def init_report_db():
    """Initializes the SQLite database for tracking batch report generation."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE generated_reports (
            report_id TEXT PRIMARY KEY,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            department TEXT NOT NULL,
            format_type TEXT NOT NULL,
            status TEXT NOT NULL
        )
    ''')

    mock_records = [
        ('rpt_1001', datetime.now().isoformat(), 'Finance', 'PDF', 'COMPLETED'),
        ('rpt_1002', datetime.now().isoformat(), 'Engineering', 'CSV', 'COMPLETED')
    ]
    cursor.executemany('''
        INSERT INTO generated_reports (report_id, created_at, department, format_type, status)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_records)

    conn.commit()
    conn.close()
    logger.info("Report tracking database initialized.")

def record_report_status(report_id: str, department: str, fmt: str, status: str):
    """Stores the metadata of a processed report task."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO generated_reports (report_id, department, format_type, status) VALUES (?, ?, ?, ?)",
            (report_id, department, fmt, status)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error recording report {report_id}: {e}")

class ReportFilterSpec:
    """Encapsulates custom report query filters and aggregation rules."""
    def __init__(self, department: str, format_type: str, date_range: tuple):
        self.department = department
        self.format_type = format_type
        self.date_range = date_range

def load_cached_filter_spec(cache_key: str, report_id: str) -> ReportFilterSpec:
    """
    SECURE: Uses standard json instead of dill to prevent Unsafe Deserialization (CWE-502).
    """
    import json

    logger.info(f"[{report_id}] Fetching secure cached report filter spec from Redis key: {cache_key}")

    try:
        raw_blob = redis_client.get(cache_key)
        if not raw_blob:
            logger.warning(f"[{report_id}] Cache miss for key: {cache_key}")
            return None

        # Secure: Replace the unsafe dill module with standard json.
        # Standard JSON only parses primitive data structures (dicts, lists, strings, numbers)
        # and strictly prevents arbitrary object instantiation or remote code execution.
        # Note: The service writing to this Redis cache must also be updated to serialize 
        # the parameters using json.dumps() and encode to UTF-8.

        payload_str = raw_blob.decode('utf-8')
        spec_dict = json.loads(payload_str)

        # Safely and manually reconstruct the ReportFilterSpec object from the parsed dictionary
        if isinstance(spec_dict, dict) and all(k in spec_dict for k in ("department", "format_type", "date_range")):
            spec = ReportFilterSpec(
                department=str(spec_dict["department"]),
                format_type=str(spec_dict["format_type"]),
                # JSON arrays deserialize to lists; convert back to tuple as expected by the class
                date_range=tuple(spec_dict["date_range"]) 
            )
            logger.debug(f"[{report_id}] Safely loaded filter spec for department: {spec.department}")
            return spec
        else:
            logger.warning(f"[{report_id}] Decoded JSON is missing required ReportFilterSpec attributes.")
            return None

    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"[{report_id}] Failed to parse Redis cache entry as JSON: {e}")
        return None
    except redis.RedisError as e:
        logger.error(f"[{report_id}] Redis connection error: {e}")
        return None
    except (ValueError, TypeError) as e:
        logger.error(f"[{report_id}] Invalid data types in cached filter spec: {e}")
        return None
    except Exception as e:
        logger.error(f"[{report_id}] Unexpected error loading filter spec: {e}")
        return None

@app.task(name="tasks.generate_department_report")
def generate_department_report(cache_key: str) -> dict:
    """Celery background task that builds a department report from cached parameters."""
    report_id = f"rpt_{uuid.uuid4().hex[:8]}"
    logger.info(f"[{report_id}] Starting background report job for key '{cache_key}'")

    spec = load_cached_filter_spec(cache_key, report_id)

    if not spec:
        record_report_status(report_id, "UNKNOWN", "UNKNOWN", "FAILED_SPEC")
        return {"report_id": report_id, "status": "FAILED", "reason": "Invalid or missing filter spec"}

    try:
        # Simulate report aggregation
        logger.info(f"[{report_id}] Compiling {spec.format_type} report for {spec.department}")
        record_report_status(report_id, spec.department, spec.format_type, "COMPLETED")
        return {
            "report_id": report_id,
            "department": spec.department,
            "format": spec.format_type,
            "status": "COMPLETED"
        }
    except Exception as e:
        logger.error(f"[{report_id}] Report compilation error: {e}")
        record_report_status(report_id, spec.department, spec.format_type, "ERROR")
        return {"report_id": report_id, "status": "ERROR"}

if __name__ == "__main__":
    init_report_db()
    logger.info("Starting Celery Report Generation Worker...")
    app.worker_main(argv=["worker", "--loglevel=info"])
