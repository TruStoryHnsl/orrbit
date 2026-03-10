"""
Background file indexer for orrbit.

Scans configured directories and maintains a SQLite database for fast queries.
Multi-root: each directory gets a 'root' slug column in the index.
"""

import logging
import sqlite3
import os
import threading
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
import mimetypes

from .files import format_size, get_file_type

logger = logging.getLogger(__name__)

# --- Configuration ---
DB_FILE: Optional[Path] = None
DB_LOCK = threading.Lock()

# --- Indexer State ---
_indexer_thread: Optional[threading.Thread] = None
_indexer_running = False
_last_scan_time = 0
_total_indexed = 0
_scan_lock = threading.Lock()


# --- Dataclass for Index Entries ---
@dataclass
class IndexEntry:
    root: str
    path: str
    name: str
    is_dir: bool
    size: int
    mtime: float
    mime: str
    file_type: str

    def to_dict(self) -> dict:
        return asdict(self)

    def to_display_dict(self) -> dict:
        """to_dict() enriched with human-readable size and mtime."""
        d = self.to_dict()
        d['size_human'] = self.size_human
        d['mtime_human'] = self.mtime_human
        return d

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'IndexEntry':
        return cls(
            root=row['root'],
            path=row['path'],
            name=row['name'],
            is_dir=bool(row['is_dir']),
            size=row['size'],
            mtime=row['mtime'],
            mime=row['mime'],
            file_type=row['file_type']
        )

    @property
    def size_human(self) -> str:
        if self.is_dir:
            return '-'
        return format_size(self.size)

    @property
    def mtime_human(self) -> str:
        return datetime.fromtimestamp(self.mtime).strftime('%Y-%m-%d %H:%M')


# --- Helper Functions ---
def get_mime_type(path: Path) -> str:
    extra_mimes = {
        '.txt': 'text/plain', '.md': 'text/markdown', '.json': 'application/json',
        '.jsonl': 'application/jsonl', '.log': 'text/plain', '.csv': 'text/csv',
        '.xml': 'text/xml', '.html': 'text/html', '.htm': 'text/html',
        '.css': 'text/css', '.js': 'text/javascript', '.py': 'text/x-python',
        '.sh': 'text/x-shellscript', '.ts': 'video/mp2t', '.m3u8': 'application/vnd.apple.mpegurl',
        '.epub': 'application/epub+zip', '.cbz': 'application/vnd.comicbook+zip',
        '.cbr': 'application/vnd.comicbook-rar',
    }
    if path.suffix.lower() in extra_mimes: return extra_mimes[path.suffix.lower()]
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    if not path.suffix:
        return 'text/plain'
    return 'application/octet-stream'


# --- Database ---

def init_db(data_dir: str):
    """Initialize the database, setting DB_FILE and creating schema."""
    global DB_FILE
    DB_FILE = Path(data_dir) / 'orrbit_index.db'
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    with DB_LOCK:
        conn = get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    root TEXT NOT NULL,
                    path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    is_dir INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    mime TEXT,
                    file_type TEXT,
                    PRIMARY KEY (root, path)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_root ON files (root);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mtime ON files (mtime);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON files (name);")
            conn.commit()
        finally:
            conn.close()


def get_connection():
    """Get a database connection with proper settings."""
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


# --- Scanning ---

def _scan_with_walk(vault_path: Path) -> dict:
    """Scan directory using os.walk().

    Returns dict of {rel_path: (mtime, size, is_dir)}.
    """
    vault_str = str(vault_path)
    entries = {}
    count = 0

    try:
        for dirpath, dirnames, filenames in os.walk(vault_str):
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]

            rel_dir = os.path.relpath(dirpath, vault_str)
            if rel_dir == '.':
                rel_dir = ''

            if rel_dir:
                try:
                    st = os.stat(dirpath)
                    entries[rel_dir] = (st.st_mtime, 0, True)
                except OSError:
                    pass

            for fname in filenames:
                if fname.startswith('.'):
                    continue
                full = os.path.join(dirpath, fname)
                try:
                    st = os.stat(full)
                    rel = os.path.join(rel_dir, fname) if rel_dir else fname
                    entries[rel] = (st.st_mtime, st.st_size, False)
                except OSError:
                    continue

                count += 1
                if count % 10000 == 0:
                    logger.info("Scan progress: %d files...", count)
    except OSError as e:
        logger.error("walk error: %s", e)

    return entries


def build_index(root_slug: str, vault_path: str) -> int:
    """Build or update the index for a single root directory."""
    global _total_indexed, _last_scan_time

    if not _scan_lock.acquire(blocking=False):
        logger.debug("Scan already in progress, skipping")
        return _total_indexed

    try:
        vault = Path(vault_path)

        try:
            if not _run_in_real_thread(vault.exists) or not _run_in_real_thread(vault.is_dir):
                logger.warning("Path not available: %s", vault)
                return 0
        except OSError as e:
            logger.warning("Path inaccessible: %s (%s)", vault, e)
            return 0

        logger.info("Starting scan of '%s'...", root_slug)
        try:
            scanned = _run_in_real_thread(_scan_with_walk, vault)
        except Exception as e:
            logger.error("Threadpool error: %s", e, exc_info=True)
            return _total_indexed

        if not scanned:
            logger.info("Scan of '%s' returned no results, skipping update", root_slug)
            return _total_indexed

        logger.info("Scan of '%s' found %d entries", root_slug, len(scanned))
        _apply_scan_to_db(root_slug, scanned)
    finally:
        _scan_lock.release()

    _last_scan_time = time.time()
    return _total_indexed


def scan_directory(root_slug: str, vault_path: str, rel_dir: str, max_depth: int = 2) -> int:
    """Scan a single directory (shallow) and update its entries in the DB."""
    global _total_indexed, _last_scan_time

    vault = Path(vault_path)
    target = vault / rel_dir if rel_dir else vault

    try:
        if not _run_in_real_thread(target.exists) or not _run_in_real_thread(target.is_dir):
            logger.warning("Target not available: %s", target)
            return 0
    except OSError as e:
        logger.warning("Target inaccessible: %s (%s)", target, e)
        return 0

    prefix = rel_dir.rstrip('/') + '/' if rel_dir else ''
    deadline = time.time() + 60

    def _do_scandir():
        result = {}
        _scandir_collect(str(target), prefix, result, depth=0, max_depth=max_depth, deadline=deadline)
        return result

    try:
        scanned = _run_in_real_thread(_do_scandir)
    except Exception as e:
        logger.error("Targeted scan failed: %s", e)
        return 0

    if rel_dir:
        try:
            st = _run_in_real_thread(target.stat)
            scanned[rel_dir] = (st.st_mtime, st.st_size, True)
        except OSError:
            pass

    _apply_scan_to_db(root_slug, scanned, scope_prefix=rel_dir, shallow_depth=max_depth)
    _last_scan_time = time.time()
    return len(scanned)


def _scandir_collect(directory: str, prefix: str, out: dict,
                     depth: int, max_depth: int, deadline: float = 0):
    """Collect entries via os.scandir()."""
    if deadline and time.time() >= deadline:
        return
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if deadline and time.time() >= deadline:
                    return
                if entry.name.startswith('.'):
                    continue
                try:
                    st = entry.stat()
                    is_dir = entry.is_dir()
                    rel_path = prefix + entry.name
                    out[rel_path] = (st.st_mtime, st.st_size if not is_dir else 0, is_dir)
                    if is_dir and depth + 1 < max_depth:
                        _scandir_collect(entry.path, rel_path + '/', out,
                                         depth + 1, max_depth, deadline)
                except OSError:
                    continue
    except OSError as e:
        logger.error("scandir error for %s: %s", directory, e)


def _apply_scan_to_db(root_slug: str, scanned: dict, scope_prefix: str | None = None, shallow_depth: int | None = None):
    """Apply scanned entries to the DB for a specific root."""
    global _total_indexed

    current_paths = set(scanned.keys())

    with DB_LOCK:
        conn = get_connection()
        try:
            cursor = conn.cursor()

            # Get existing entries for this root (scoped or full)
            existing = {}
            if scope_prefix is not None:
                if scope_prefix:
                    for row in cursor.execute(
                        "SELECT path, mtime, size FROM files WHERE root = ? AND (path = ? OR path LIKE ? || '/%')",
                        (root_slug, scope_prefix, scope_prefix)
                    ):
                        existing[row[0]] = (row[1], row[2])
                else:
                    for row in cursor.execute(
                        "SELECT path, mtime, size FROM files WHERE root = ? AND INSTR(path, '/') = 0",
                        (root_slug,)
                    ):
                        existing[row[0]] = (row[1], row[2])
            else:
                for row in cursor.execute(
                    "SELECT path, mtime, size FROM files WHERE root = ?",
                    (root_slug,)
                ):
                    existing[row[0]] = (row[1], row[2])

            # Upsert changed entries
            to_upsert = []
            for rel_path, (mtime, size, is_dir) in scanned.items():
                old = existing.get(rel_path)
                if old and abs(old[0] - mtime) < 0.01 and old[1] == size:
                    continue
                name = rel_path.rsplit('/', 1)[-1]
                mime = '' if is_dir else get_mime_type(Path(rel_path))
                ft = 'dir' if is_dir else get_file_type(mime)
                to_upsert.append((root_slug, rel_path, name, is_dir, size, mtime, mime, ft))

            if to_upsert:
                cursor.executemany("""
                    INSERT OR REPLACE INTO files (root, path, name, is_dir, size, mtime, mime, file_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, to_upsert)
                logger.info("Updated %d entries in '%s'", len(to_upsert), root_slug)

            # Remove deleted paths
            deleted_paths = set(existing.keys()) - current_paths
            if shallow_depth is not None and scope_prefix is not None:
                prefix_depth = scope_prefix.count('/') if scope_prefix else 0
                deleted_paths = {
                    p for p in deleted_paths
                    if p.count('/') - prefix_depth <= shallow_depth
                }
            if deleted_paths:
                cursor.executemany("DELETE FROM files WHERE root = ? AND path = ?",
                                   [(root_slug, p) for p in deleted_paths])
                logger.info("Removed %d stale entries from '%s'", len(deleted_paths), root_slug)

            conn.commit()
            _total_indexed = cursor.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        finally:
            conn.close()


def query_index(
    root: str,
    directory: str = '',
    query: str = '',
    file_type: str = '',
    sort_by: str = 'name',
    sort_desc: bool = False,
    page: int = 1,
    per_page: int = 50,
    recursive: bool = False,
) -> tuple[list[IndexEntry], int]:
    """Query the index with filters and pagination, scoped to a root."""
    params = [root]
    where_clauses = ["root = ?"]

    # Directory filter
    if directory:
        if recursive:
            where_clauses.append("path LIKE ? || '/%'")
            params.append(directory)
        else:
            where_clauses.append("path LIKE ? || '/%' AND INSTR(SUBSTR(path, LENGTH(?) + 2), '/') = 0")
            params.extend([directory, directory])
    else:
        if not recursive:
            where_clauses.append("INSTR(path, '/') = 0")

    if query:
        where_clauses.append("name LIKE ?")
        params.append(f'%{query}%')

    if file_type:
        if ',' in file_type:
            types = [t.strip() for t in file_type.split(',')]
            placeholders = ','.join('?' * len(types))
            where_clauses.append(f"file_type IN ({placeholders})")
            params.extend(types)
        else:
            where_clauses.append("file_type = ?")
            params.append(file_type)

    where_sql = "WHERE " + " AND ".join(where_clauses)

    sort_map = {'name': 'name', 'size': 'size', 'date': 'mtime', 'type': 'file_type, name'}
    order_by_sql = f"ORDER BY {sort_map.get(sort_by, 'mtime')} {'DESC' if sort_desc else 'ASC'}"

    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        count_sql = f"SELECT COUNT(*) FROM files {where_sql}"
        total = cursor.execute(count_sql, params).fetchone()[0]

        offset = (page - 1) * per_page
        query_sql = f"SELECT * FROM files {where_sql} {order_by_sql} LIMIT ? OFFSET ?"
        results = cursor.execute(query_sql, params + [per_page, offset]).fetchall()

        entries = [IndexEntry.from_row(row) for row in results]
    finally:
        conn.close()

    return entries, total


# --- Background Thread Management ---

def _run_in_real_thread(fn, *args):
    """Run fn in a real OS thread so NFS I/O doesn't block gevent."""
    try:
        from gevent import get_hub
        return get_hub().threadpool.apply(fn, args)
    except Exception:
        return fn(*args)


def start_background_indexer(directories: dict[str, str], interval: int = 1800):
    """Start the background indexer for all configured directories.

    directories: {slug: abs_path}
    """
    global _indexer_thread, _indexer_running
    if _indexer_running:
        return

    def indexer_loop():
        global _indexer_running, _total_indexed
        _indexer_running = True

        # Check if DB already has data
        try:
            conn = get_connection()
            existing = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            conn.close()
        except Exception:
            existing = 0

        if existing > 0:
            _total_indexed = existing
            logger.info("Using existing index (%d files), first scan in 120s", existing)
            for _ in range(120):
                if not _indexer_running: break
                time.sleep(1)
        else:
            time.sleep(5)

        while _indexer_running:
            for slug, path in directories.items():
                if not _indexer_running:
                    break
                try:
                    count = build_index(slug, path)
                    logger.info("Indexed '%s': %d total files", slug, count)
                except Exception as e:
                    logger.error("Error indexing '%s': %s", slug, e)
            for _ in range(interval):
                if not _indexer_running: break
                time.sleep(1)

    _indexer_thread = threading.Thread(target=indexer_loop, daemon=True)
    _indexer_thread.start()


def stop_background_indexer():
    """Stop the background indexer."""
    global _indexer_running
    _indexer_running = False


def search_all_roots(
    query: str,
    file_type: str = '',
    sort_by: str = 'name',
    sort_desc: bool = False,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[IndexEntry], int]:
    """Search across all roots for matching filenames."""
    if not query:
        return [], 0

    params = []
    where_clauses = ["name LIKE ?"]
    params.append(f'%{query}%')

    if file_type:
        if ',' in file_type:
            types = [t.strip() for t in file_type.split(',')]
            placeholders = ','.join('?' * len(types))
            where_clauses.append(f"file_type IN ({placeholders})")
            params.extend(types)
        else:
            where_clauses.append("file_type = ?")
            params.append(file_type)

    where_sql = "WHERE " + " AND ".join(where_clauses)

    sort_map = {'name': 'name', 'size': 'size', 'date': 'mtime', 'type': 'file_type, name'}
    order_by_sql = f"ORDER BY {sort_map.get(sort_by, 'mtime')} {'DESC' if sort_desc else 'ASC'}"

    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        total = cursor.execute(f"SELECT COUNT(*) FROM files {where_sql}", params).fetchone()[0]

        offset = (page - 1) * per_page
        results = cursor.execute(
            f"SELECT * FROM files {where_sql} {order_by_sql} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        entries = [IndexEntry.from_row(row) for row in results]
    finally:
        conn.close()

    return entries, total


def get_indexer_status() -> dict:
    """Get current indexer status."""
    global _total_indexed, _last_scan_time
    if DB_FILE and DB_FILE.exists():
        conn = get_connection()
        try:
            _total_indexed = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        finally:
            conn.close()
    return {
        'running': _indexer_running,
        'total_indexed': _total_indexed,
        'last_scan': _last_scan_time,
        'last_scan_human': datetime.fromtimestamp(_last_scan_time).strftime('%Y-%m-%d %H:%M:%S') if _last_scan_time else 'Never',
        'index_file': str(DB_FILE) if DB_FILE else None,
        'index_exists': DB_FILE.exists() if DB_FILE else False,
    }
