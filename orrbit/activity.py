"""
Activity log for orrbit.

Logs user actions (downloads, uploads, share creation, logins) to SQLite.
"""

import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_FILE: Optional[Path] = None
DB_LOCK = threading.Lock()


def init_activity_db(data_dir: str):
    """Initialize the activity log table."""
    global DB_FILE
    DB_FILE = Path(data_dir) / 'orrbit_index.db'

    with DB_LOCK:
        conn = _get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    username TEXT NOT NULL,
                    details TEXT,
                    ip TEXT,
                    timestamp REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_log (timestamp);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_log (action);")
            conn.commit()
        finally:
            conn.close()


def _get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.row_factory = sqlite3.Row
    return conn


def log_action(action: str, username: str, details: str = '', ip: str = ''):
    """Log an activity."""
    if not DB_FILE:
        return
    with DB_LOCK:
        conn = _get_connection()
        try:
            conn.execute(
                "INSERT INTO activity_log (action, username, details, ip, timestamp) VALUES (?, ?, ?, ?, ?)",
                (action, username, details, ip, time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def get_activity(
    action: str = '',
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict], int]:
    """Get activity log entries with optional filtering."""
    if not DB_FILE:
        return [], 0

    params = []
    where = ""
    if action:
        where = "WHERE action = ?"
        params.append(action)

    conn = _get_connection()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM activity_log {where}", params).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT * FROM activity_log {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        entries = []
        for r in rows:
            entries.append({
                'id': r['id'],
                'action': r['action'],
                'username': r['username'],
                'details': r['details'],
                'ip': r['ip'],
                'timestamp': r['timestamp'],
                'time_human': datetime.fromtimestamp(r['timestamp']).strftime('%Y-%m-%d %H:%M'),
            })
    finally:
        conn.close()

    return entries, total
