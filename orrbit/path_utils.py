"""
Shared path resolution utilities for orrbit.

Centralizes slug validation, directory traversal checks, and safe query parsing.
"""

from pathlib import Path
from flask import abort, current_app


def resolve_path(slug: str, rel_path: str = '') -> tuple[str, Path]:
    """Validate slug and resolve absolute path.

    Returns (abs_root_str, target_path).
    Aborts with 404 if slug unknown, 403 if path traversal detected.
    """
    directory_map = current_app.config['DIRECTORY_MAP']
    if slug not in directory_map:
        abort(404)

    abs_root = Path(directory_map[slug])
    target = abs_root / rel_path if rel_path else abs_root

    # Prevent directory traversal
    try:
        target.resolve().relative_to(abs_root.resolve())
    except ValueError:
        abort(403)

    return str(abs_root), target


def resolve_path_or_none(slug: str, rel_path: str) -> Path | None:
    """Resolve a slug + relative path without aborting.

    Returns the resolved Path, or None if the slug is unknown
    or the path escapes the root.
    """
    directory_map = current_app.config['DIRECTORY_MAP']
    if slug not in directory_map:
        return None
    abs_root = Path(directory_map[slug])
    target = abs_root / rel_path
    try:
        target.resolve().relative_to(abs_root.resolve())
    except ValueError:
        return None
    return target


def safe_int(value, default: int, min_val: int = None, max_val: int = None) -> int:
    """Safely parse a value to int with bounds clamping.

    Returns default if conversion fails.
    """
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if min_val is not None:
        result = max(result, min_val)
    if max_val is not None:
        result = min(result, max_val)
    return result
