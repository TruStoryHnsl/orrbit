"""
Playhead persistence for orrbit.

Saves video/audio playback position and PDF page number per user.
"""

import time
from typing import Optional

from .json_store import JsonStore

_store = JsonStore('playhead')
init_playhead = _store.init


def save_position(username: str, root: str, file_path: str, position: float):
    """Save playback position for a file."""
    with _store.lock:
        data = _store.load(username)
        k = _store.key(root, file_path)
        data[k] = {'position': position, 'updated': time.time()}
        _store.save(username, data)


def get_position(username: str, root: str, file_path: str) -> Optional[float]:
    """Get saved playback position. Returns None if not saved."""
    data = _store.load(username)
    entry = data.get(_store.key(root, file_path))
    if entry:
        return entry.get('position')
    return None


def clear_position(username: str, root: str, file_path: str):
    """Clear saved position for a file."""
    with _store.lock:
        data = _store.load(username)
        k = _store.key(root, file_path)
        if k in data:
            del data[k]
            _store.save(username, data)
