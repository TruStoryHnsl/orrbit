"""
Per-user favorites for orrbit.

Stores favorite files/folders in JSON files per user.
"""

from .json_store import JsonStore

_store = JsonStore('favorites')
init_favorites = _store.init


def toggle_favorite(username: str, root: str, file_path: str, name: str,
                    is_dir: bool = False, file_type: str = '') -> bool:
    """Toggle a favorite. Returns True if now favorited, False if removed."""
    with _store.lock:
        data = _store.load(username)
        k = _store.key(root, file_path)
        if k in data:
            del data[k]
            _store.save(username, data)
            return False
        else:
            data[k] = {
                'root': root,
                'path': file_path,
                'name': name,
                'is_dir': is_dir,
                'file_type': file_type,
            }
            _store.save(username, data)
            return True


def is_favorited(username: str, root: str, file_path: str) -> bool:
    """Check if a file is favorited."""
    data = _store.load(username)
    return _store.key(root, file_path) in data


def list_favorites(username: str) -> list[dict]:
    """List all favorites for a user."""
    data = _store.load(username)
    return list(data.values())
