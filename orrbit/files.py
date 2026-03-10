"""
File system utilities for orrbit.

Handles directory listing, file info, and MIME type detection.
"""

import os
import mimetypes
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime

# Initialize mimetypes
mimetypes.init()

# Additional MIME types not in standard library
EXTRA_MIMES = {
    '.txt': 'text/plain',
    '.md': 'text/markdown',
    '.json': 'application/json',
    '.jsonl': 'application/jsonl',
    '.log': 'text/plain',
    '.csv': 'text/csv',
    '.xml': 'text/xml',
    '.html': 'text/html',
    '.htm': 'text/html',
    '.css': 'text/css',
    '.js': 'text/javascript',
    '.py': 'text/x-python',
    '.sh': 'text/x-shellscript',
    '.ts': 'video/mp2t',
    '.m3u8': 'application/vnd.apple.mpegurl',
    '.epub': 'application/epub+zip',
    '.cbz': 'application/vnd.comicbook+zip',
    '.cbr': 'application/vnd.comicbook-rar',
}


@dataclass
class FileInfo:
    """Information about a file or directory."""
    name: str
    path: str           # Relative to vault
    abs_path: str       # Absolute path
    is_dir: bool
    size: int           # Bytes (0 for dirs)
    mtime: float        # Unix timestamp
    mime: str           # MIME type (empty for dirs)

    @property
    def size_human(self) -> str:
        """Human-readable file size."""
        if self.is_dir:
            return '-'
        return format_size(self.size)

    @property
    def mtime_human(self) -> str:
        """Human-readable modification time."""
        dt = datetime.fromtimestamp(self.mtime)
        return dt.strftime('%Y-%m-%d %H:%M')

    @property
    def file_type(self) -> str:
        """Category for icons: dir, text, image, video, audio, pdf, epub, other."""
        if self.is_dir:
            return 'dir'
        return get_file_type(self.mime)


def format_size(size: int) -> str:
    """Human-readable file size (standalone version)."""
    s = float(size)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if s < 1024:
            return f"{s:.1f} {unit}" if unit != 'B' else f"{int(s)} B"
        s /= 1024
    return f"{s:.1f} PB"


def get_file_type(mime: str) -> str:
    """Categorize a MIME type: text, image, video, audio, pdf, epub, comic, or other."""
    if not mime:
        return 'other'
    main_type = mime.split('/')[0]
    if main_type in ('text', 'image', 'video', 'audio'):
        return main_type
    if mime == 'application/pdf':
        return 'pdf'
    if mime == 'application/epub+zip':
        return 'epub'
    if mime in ('application/vnd.comicbook+zip', 'application/vnd.comicbook-rar'):
        return 'comic'
    if mime in ('application/json', 'application/jsonl', 'text/markdown'):
        return 'text'
    return 'other'


def is_text_file(path: Path, sample_size: int = 8192) -> bool:
    """Check if a file appears to be text by reading a sample."""
    try:
        with open(path, 'rb') as f:
            sample = f.read(sample_size)
        if not sample:
            return True  # Empty file is text
        # Check for null bytes (binary indicator)
        if b'\x00' in sample:
            return False
        # Try to decode as UTF-8
        try:
            sample.decode('utf-8')
            return True
        except UnicodeDecodeError:
            # Try latin-1 (always succeeds but check for control chars)
            text = sample.decode('latin-1')
            # If mostly printable/whitespace, it's probably text
            printable = sum(1 for c in text if c.isprintable() or c.isspace())
            return printable / len(text) > 0.85
    except (OSError, PermissionError):
        return False


def get_mime_type(path: Path) -> str:
    """Get MIME type for a file."""
    suffix = path.suffix.lower()
    if suffix in EXTRA_MIMES:
        return EXTRA_MIMES[suffix]
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    # No extension or unknown - check if it's a text file
    if is_text_file(path):
        return 'text/plain'
    return 'application/octet-stream'


def get_file_info(abs_path: Path, vault_path: Path) -> FileInfo:
    """Get FileInfo for a path."""
    try:
        stat = abs_path.stat()
        is_dir = abs_path.is_dir()
        rel_path = str(abs_path.relative_to(vault_path))

        return FileInfo(
            name=abs_path.name,
            path=rel_path,
            abs_path=str(abs_path),
            is_dir=is_dir,
            size=0 if is_dir else stat.st_size,
            mtime=stat.st_mtime,
            mime='' if is_dir else get_mime_type(abs_path),
        )
    except (OSError, PermissionError):
        return None


def get_breadcrumbs(rel_path: str) -> list[tuple[str, str]]:
    """
    Get breadcrumb navigation for a path.

    Returns list of (name, path) tuples.
    """
    if not rel_path:
        return []

    parts = Path(rel_path).parts
    breadcrumbs = []
    current = ''

    for part in parts:
        current = str(Path(current) / part) if current else part
        breadcrumbs.append((part, current))

    return breadcrumbs


def reflow_text(text: str) -> str:
    """
    Reflow hard-wrapped text into proper paragraphs.

    Joins lines within paragraphs while preserving:
    - Paragraph breaks (blank lines)
    - Indented lines (start new paragraph)
    - Short lines followed by blank (likely intentional)
    """
    import re

    lines = text.split('\n')
    paragraphs = []
    current = []

    for i, line in enumerate(lines):
        stripped = line.rstrip()

        # Blank line = paragraph break
        if not stripped:
            if current:
                paragraphs.append(' '.join(current))
                current = []
            paragraphs.append('')
            continue

        # Check if this line starts a new paragraph
        starts_new = (
            not current or  # First line
            line.startswith((' ', '\t')) or  # Indented
            stripped.startswith(('*', '-', '~', '–')) or  # Bullet
            re.match(r'^\d+[\.\)]\s', stripped) or  # Numbered list
            re.match(r'^[A-Z][A-Z\s]+:?\s*$', stripped) or  # ALL CAPS header
            (current and len(current[-1]) < 40)  # Previous line was short
        )

        if starts_new and current:
            paragraphs.append(' '.join(current))
            current = []

        current.append(stripped)

    # Don't forget last paragraph
    if current:
        paragraphs.append(' '.join(current))

    # Remove trailing empty paragraphs, keep internal ones for spacing
    while paragraphs and not paragraphs[-1]:
        paragraphs.pop()
    return '\n\n'.join(paragraphs)


def read_text_file(vault_path: str, rel_path: str, max_size: int = 10_000_000, reflow: bool = True) -> str:
    """
    Read a text file's contents.

    Returns file contents or raises error.
    """
    vault = Path(vault_path)
    target = vault / rel_path

    if not target.exists():
        raise FileNotFoundError(f"File not found: {rel_path}")
    if target.is_dir():
        raise IsADirectoryError(f"Cannot read directory: {rel_path}")

    # Security check
    try:
        target.resolve().relative_to(vault.resolve())
    except ValueError:
        raise PermissionError("Access denied: path outside vault")

    # Size check
    size = target.stat().st_size
    if size > max_size:
        raise ValueError(f"File too large: {size} bytes (max {max_size})")

    # Try to read as text
    try:
        content = target.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        content = target.read_text(encoding='latin-1')

    if reflow:
        content = reflow_text(content)

    return content
