"""
Shareable download links for orrbit.

Tokenized URLs with server-side expiration. No login required to download.
"""

import logging
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_FILE: Optional[Path] = None
DB_LOCK = threading.Lock()

DEFAULT_TTL = 1800  # 30 minutes

_cleanup_thread: Optional[threading.Thread] = None
_cleanup_running = False


@dataclass
class ShareLink:
    token: str
    root: str
    file_path: str
    created_at: float
    expires_at: float
    created_by: str

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def created_at_human(self) -> str:
        return datetime.fromtimestamp(self.created_at).strftime('%Y-%m-%d %H:%M')

    @property
    def expires_at_human(self) -> str:
        return datetime.fromtimestamp(self.expires_at).strftime('%Y-%m-%d %H:%M')

    @property
    def remaining_minutes(self) -> int:
        return max(0, int((self.expires_at - time.time()) / 60))

    @property
    def filename(self) -> str:
        return self.file_path.rsplit('/', 1)[-1] if '/' in self.file_path else self.file_path

    def to_dict(self) -> dict:
        return {
            'token': self.token,
            'root': self.root,
            'file_path': self.file_path,
            'filename': self.filename,
            'created_at': self.created_at,
            'created_at_human': self.created_at_human,
            'expires_at': self.expires_at,
            'expires_at_human': self.expires_at_human,
            'remaining_minutes': self.remaining_minutes,
            'expired': self.expired,
            'created_by': self.created_by,
        }


def _get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.row_factory = sqlite3.Row
    return conn


def init_shares_db(data_dir: str):
    """Initialize the share links table."""
    global DB_FILE
    DB_FILE = Path(data_dir) / 'orrbit_index.db'

    with DB_LOCK:
        conn = _get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS share_links (
                    token TEXT PRIMARY KEY,
                    root TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    created_by TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_share_expires ON share_links (expires_at);")
            conn.commit()
        finally:
            conn.close()


def create_share_link(root: str, file_path: str, created_by: str, ttl: int = DEFAULT_TTL) -> ShareLink:
    """Create a new share link. Returns the ShareLink."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    expires_at = now + ttl

    with DB_LOCK:
        conn = _get_connection()
        try:
            conn.execute(
                "INSERT INTO share_links (token, root, file_path, created_at, expires_at, created_by) VALUES (?, ?, ?, ?, ?, ?)",
                (token, root, file_path, now, expires_at, created_by),
            )
            conn.commit()
        finally:
            conn.close()

    return ShareLink(token=token, root=root, file_path=file_path,
                     created_at=now, expires_at=expires_at, created_by=created_by)


def get_share_link(token: str) -> Optional[ShareLink]:
    """Look up a share link by token. Returns None if not found."""
    conn = _get_connection()
    try:
        row = conn.execute("SELECT * FROM share_links WHERE token = ?", (token,)).fetchone()
        if not row:
            return None
        return ShareLink(
            token=row['token'], root=row['root'], file_path=row['file_path'],
            created_at=row['created_at'], expires_at=row['expires_at'],
            created_by=row['created_by'],
        )
    finally:
        conn.close()


def list_share_links(created_by: str = None) -> list[ShareLink]:
    """List active (non-expired) share links, optionally filtered by creator."""
    now = time.time()
    conn = _get_connection()
    try:
        if created_by:
            rows = conn.execute(
                "SELECT * FROM share_links WHERE expires_at > ? AND created_by = ? ORDER BY created_at DESC",
                (now, created_by),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM share_links WHERE expires_at > ? ORDER BY created_at DESC",
                (now,),
            ).fetchall()
        return [
            ShareLink(token=r['token'], root=r['root'], file_path=r['file_path'],
                      created_at=r['created_at'], expires_at=r['expires_at'],
                      created_by=r['created_by'])
            for r in rows
        ]
    finally:
        conn.close()


def revoke_share_link(token: str) -> bool:
    """Delete a share link. Returns True if it existed."""
    with DB_LOCK:
        conn = _get_connection()
        try:
            cursor = conn.execute("DELETE FROM share_links WHERE token = ?", (token,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def cleanup_expired():
    """Remove expired share links from the database."""
    with DB_LOCK:
        conn = _get_connection()
        try:
            deleted = conn.execute(
                "DELETE FROM share_links WHERE expires_at < ?", (time.time(),)
            ).rowcount
            conn.commit()
            if deleted:
                logger.info("Cleaned up %d expired link(s)", deleted)
        finally:
            conn.close()


def start_cleanup_thread(interval: int = 300):
    """Start background thread that cleans expired links every `interval` seconds."""
    global _cleanup_thread, _cleanup_running
    if _cleanup_running:
        return

    def loop():
        global _cleanup_running
        _cleanup_running = True
        time.sleep(60)  # Initial delay
        while _cleanup_running:
            try:
                cleanup_expired()
            except Exception as e:
                logger.error("Cleanup error: %s", e)
            for _ in range(interval):
                if not _cleanup_running:
                    break
                time.sleep(1)

    _cleanup_thread = threading.Thread(target=loop, daemon=True)
    _cleanup_thread.start()
