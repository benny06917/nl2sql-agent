
import re
import sqlite3
from pathlib import Path


class UnsafeQueryError(Exception):
    """Raised when a generated query is not a read-only SELECT."""

_FORBIDDEN = {
    "insert", "update", "delete", "drop", "alter", "create",
    "replace", "truncate", "attach", "detach", "pragma",
    "grant", "revoke", "vacuum",
}


def get_connection(db_path: str) -> sqlite3.Connection:
    """Open the SQLite file in read-only mode via a URI."""
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def is_safe_sql(sql: str) -> bool:

    cleaned = re.sub(r"--.*?$", " ", sql, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip().rstrip(";").strip()

    if not cleaned:
        return False
    if ";" in cleaned:
        return False
    if not re.match(r"^(select|with)\b", cleaned, flags=re.IGNORECASE):
        return False
    tokens = set(re.findall(r"[a-zA-Z_]+", cleaned.lower()))
    if tokens & _FORBIDDEN:
        return False
    return True


def get_schema(conn: sqlite3.Connection) -> str:

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    lines: list[str] = []
    for (table,) in tables:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        col_desc = ", ".join(f"{c[1]} {c[2]}" for c in cols)
        lines.append(f"{table}({col_desc})")
    return "\n".join(lines)


def execute_query(conn: sqlite3.Connection, sql: str, max_rows: int = 50):

    if not is_safe_sql(sql):
        raise UnsafeQueryError("Only read-only SELECT queries are allowed.")

    cur = conn.execute(sql)
    columns = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchmany(max_rows)
    return columns, rows
