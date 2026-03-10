"""
Shared JSON file storage for orrbit.

Thread-safe per-user JSON file storage used by favorites, tags, and playhead.
"""

import json
import os
import threading
from pathlib import Path
from typing import Optional


class JsonStore:
    """Thread-safe per-user JSON storage backed by individual files."""

    def __init__(self, subdirectory: str):
        self._subdir = subdirectory
        self._data_dir: Optional[Path] = None
        self._lock = threading.Lock()

    def init(self, data_dir: str):
        """Initialize with data directory, creating subdirectory if needed."""
        self._data_dir = Path(data_dir) / self._subdir
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _user_file(self, username: str) -> Path:
        return self._data_dir / f'{username}.json'

    def load(self, username: str) -> dict:
        """Load user data from JSON file. Returns empty dict on error."""
        path = self._user_file(username)
        if not path.exists():
            return {}
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}

    def save(self, username: str, data: dict):
        """Atomically save user data to JSON file."""
        path = self._user_file(username)
        tmp = path.with_suffix('.tmp')
        try:
            with open(tmp, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        except OSError:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)

    @staticmethod
    def key(root: str, file_path: str) -> str:
        """Build a composite key from root slug and file path."""
        return f'{root}:{file_path}'

    @property
    def lock(self) -> threading.Lock:
        return self._lock
