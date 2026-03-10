"""
Per-user file tagging for orrbit.

Stores tags in JSON files per user. Each file can have multiple custom tags.
"""

from .json_store import JsonStore

_store = JsonStore('tags')
init_tags = _store.init


def add_tag(username: str, root: str, file_path: str, tag: str) -> list[str]:
    """Add a tag to a file. Returns updated tag list."""
    tag = tag.strip().lower()
    if not tag:
        return get_tags(username, root, file_path)
    with _store.lock:
        data = _store.load(username)
        k = _store.key(root, file_path)
        tags = data.get(k, [])
        if tag not in tags:
            tags.append(tag)
            data[k] = tags
            _store.save(username, data)
        return tags


def remove_tag(username: str, root: str, file_path: str, tag: str) -> list[str]:
    """Remove a tag from a file. Returns updated tag list."""
    tag = tag.strip().lower()
    with _store.lock:
        data = _store.load(username)
        k = _store.key(root, file_path)
        tags = data.get(k, [])
        if tag in tags:
            tags.remove(tag)
            if tags:
                data[k] = tags
            else:
                del data[k]
            _store.save(username, data)
        return tags


def get_tags(username: str, root: str, file_path: str) -> list[str]:
    """Get tags for a file."""
    data = _store.load(username)
    return data.get(_store.key(root, file_path), [])


def list_all_tags(username: str) -> list[str]:
    """Get all unique tags used by a user."""
    data = _store.load(username)
    tags = set()
    for tag_list in data.values():
        tags.update(tag_list)
    return sorted(tags)


def get_all_tags_map(username: str) -> dict:
    """Get the full tag map for a user. Returns {root:path -> [tags]}."""
    return _store.load(username)


def find_by_tag(username: str, tag: str) -> list[dict]:
    """Find all files with a given tag. Returns list of {root, path}."""
    tag = tag.strip().lower()
    data = _store.load(username)
    results = []
    for k, tags in data.items():
        if tag in tags:
            root, path = k.split(':', 1)
            results.append({'root': root, 'path': path})
    return results
