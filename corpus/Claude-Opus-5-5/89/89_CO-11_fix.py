import os
import logging
from datetime import date, datetime
from decimal import Decimal
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

import mysql.connector
from mysql.connector import pooling

DB_CONFIG = {
    "host": os.environ.get("HR_DB_HOST", "localhost"),
    "user": os.environ.get("HR_DB_USER", "hr_reader"),
    "password": os.environ.get("HR_DB_PASSWORD", ""),
    "database": os.environ.get("HR_DB_NAME", "hr"),
}
LISTEN_HOST = os.environ.get("DIRECTORY_RPC_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("DIRECTORY_RPC_PORT", "8730"))
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("directory-rpc")

pool = pooling.MySQLConnectionPool(pool_name="directory", pool_size=5, **DB_CONFIG)


class DirectoryRequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ("/RPC2",)


def clean(row):
    out = {}
    for key, value in row.items():
        if isinstance(value, (date, datetime)):
            out[key] = value.isoformat()
        elif isinstance(value, Decimal):
            out[key] = str(value)
        elif value is None:
            out[key] = ""
        else:
            out[key] = value
    return out


def query(sql, params=()):
    conn = pool.get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
        return [clean(r) for r in rows]
    finally:
        conn.close()


def list_departments():
    return query(
        "SELECT d.code, d.name, COUNT(e.id) AS headcount FROM departments d "
        "LEFT JOIN employees e ON e.department_id = d.id AND e.active = 1 "
        "GROUP BY d.id ORDER BY d.name"
    )


def department_staff(department_code, page=1, page_size=DEFAULT_PAGE_SIZE):
    try:
        page = max(1, int(page))
        page_size = int(page_size)
    except (TypeError, ValueError):
        raise ValueError("page and page_size must be whole numbers")
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    offset = (page - 1) * page_size
    sql = (
        "SELECT e.employee_no, e.display_name, e.job_title, e.office, e.extension "
        "FROM employees e JOIN departments d ON d.id = e.department_id "
        "WHERE d.code = %s AND e.active = 1 "
        "ORDER BY e.display_name "
        "LIMIT %s OFFSET %s"
    )
    staff = query(sql, (str(department_code), page_size, offset))
    return {"department": department_code, "page": page, "staff": staff}


def lookup_extension(extension):
    rows = query(
        "SELECT employee_no, display_name, job_title, office FROM employees "
        "WHERE extension = %s AND active = 1",
        (str(extension).strip(),),
    )
    return rows[0] if rows else {}


def find_by_name(fragment):
    fragment = str(fragment).strip()
    if len(fragment) < 2:
        raise ValueError("search with at least two characters")
    escaped = fragment.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return query(
        "SELECT employee_no, display_name, job_title, extension FROM employees "
        "WHERE active = 1 AND display_name LIKE %s ORDER BY display_name LIMIT 30",
        (f"%{escaped}%",),
    )


def ping():
    return {"ok": True, "time": datetime.now().isoformat(timespec="seconds")}


def main():
    server = SimpleXMLRPCServer(
        (LISTEN_HOST, LISTEN_PORT),
        requestHandler=DirectoryRequestHandler,
        allow_none=False,
        logRequests=False,
    )
    server.register_introspection_functions()
    server.register_function(list_departments, "directory.departments")
    server.register_function(department_staff, "directory.staff")
    server.register_function(lookup_extension, "directory.extension")
    server.register_function(find_by_name, "directory.search")
    server.register_function(ping, "system.ping")
    log.info("Staff directory XML-RPC on %s:%d", LISTEN_HOST, LISTEN_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Stopping")


if __name__ == "__main__":
    main()