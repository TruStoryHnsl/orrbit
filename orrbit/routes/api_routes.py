"""API routes for Phase 5 features: favorites, tags, playhead, batch, activity."""

import io
import shutil
import sqlite3
import zipfile
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file, abort, current_app, render_template
from flask_login import login_required, current_user

from ..favorites import toggle_favorite, is_favorited, list_favorites
from ..tags import add_tag, remove_tag, get_tags, list_all_tags, find_by_tag, get_all_tags_map
from ..playhead import save_position, get_position
from ..activity import log_action, get_activity
from ..indexer import get_connection, IndexEntry
from ..path_utils import resolve_path_or_none, safe_int

bp = Blueprint('api', __name__)


# --- Favorites ---

@bp.route('/api/favorites', methods=['GET'])
@login_required
def api_favorites_list():
    """List all favorites for current user."""
    favs = list_favorites(current_user.username)
    return jsonify({'favorites': favs})


@bp.route('/api/favorites', methods=['POST'])
@login_required
def api_favorites_toggle():
    """Toggle favorite for a file."""
    data = request.get_json(silent=True) or {}
    root = data.get('root', '')
    file_path = data.get('path', '')
    name = data.get('name', '')
    is_dir = data.get('is_dir', False)
    file_type = data.get('file_type', '')

    if not root or not file_path:
        return jsonify({'error': 'Missing root or path'}), 400

    if not name:
        name = file_path.rsplit('/', 1)[-1] if '/' in file_path else file_path

    now_favorited = toggle_favorite(
        current_user.username, root, file_path, name,
        is_dir=is_dir, file_type=file_type,
    )

    action_word = 'favorited' if now_favorited else 'unfavorited'
    log_action(action_word, current_user.username, f'{root}:{file_path}',
               ip=request.remote_addr)

    return jsonify({'favorited': now_favorited})


@bp.route('/api/favorites/check', methods=['GET'])
@login_required
def api_favorites_check():
    """Check if a file is favorited."""
    root = request.args.get('root', '')
    file_path = request.args.get('path', '')
    if not root or not file_path:
        return jsonify({'favorited': False})
    return jsonify({'favorited': is_favorited(current_user.username, root, file_path)})


# --- Tags ---

@bp.route('/api/tags', methods=['GET'])
@login_required
def api_tags_list():
    """List all tags used by current user."""
    tags = list_all_tags(current_user.username)
    return jsonify({'tags': tags})


@bp.route('/api/tags/all', methods=['GET'])
@login_required
def api_tags_all():
    """Get full tag map for current user (for tag mode bulk lookup)."""
    data = get_all_tags_map(current_user.username)
    return jsonify({'tags_map': data})


@bp.route('/api/tags/file', methods=['GET'])
@login_required
def api_tags_for_file():
    """Get tags for a specific file."""
    root = request.args.get('root', '')
    file_path = request.args.get('path', '')
    if not root or not file_path:
        return jsonify({'tags': []})
    tags = get_tags(current_user.username, root, file_path)
    return jsonify({'tags': tags})


@bp.route('/api/tags/add', methods=['POST'])
@login_required
def api_tags_add():
    """Add a tag to a file."""
    data = request.get_json(silent=True) or {}
    root = data.get('root', '')
    file_path = data.get('path', '')
    tag = data.get('tag', '')

    if not root or not file_path or not tag:
        return jsonify({'error': 'Missing root, path, or tag'}), 400

    tags = add_tag(current_user.username, root, file_path, tag)
    log_action('tag', current_user.username, f'{root}:{file_path} +{tag}',
               ip=request.remote_addr)
    return jsonify({'tags': tags})


@bp.route('/api/tags/remove', methods=['POST'])
@login_required
def api_tags_remove():
    """Remove a tag from a file."""
    data = request.get_json(silent=True) or {}
    root = data.get('root', '')
    file_path = data.get('path', '')
    tag = data.get('tag', '')

    if not root or not file_path or not tag:
        return jsonify({'error': 'Missing root, path, or tag'}), 400

    tags = remove_tag(current_user.username, root, file_path, tag)
    return jsonify({'tags': tags})


@bp.route('/api/tags/find', methods=['GET'])
@login_required
def api_tags_find():
    """Find all files with a given tag."""
    tag = request.args.get('tag', '')
    if not tag:
        return jsonify({'items': []})

    results = find_by_tag(current_user.username, tag)

    # Enrich with file metadata from index
    items = []
    if results:
        conn = get_connection()
        try:
            conn.row_factory = sqlite3.Row
            for r in results:
                row = conn.execute(
                    "SELECT * FROM files WHERE root = ? AND path = ?",
                    (r['root'], r['path']),
                ).fetchone()
                if row:
                    entry = IndexEntry.from_row(row)
                    items.append(entry.to_display_dict())
        finally:
            conn.close()

    return jsonify({'items': items, 'tag': tag, 'total': len(items)})


# --- Playhead ---

@bp.route('/api/playhead', methods=['POST'])
@login_required
def api_playhead_save():
    """Save playback position."""
    data = request.get_json(silent=True) or {}
    root = data.get('root', '')
    file_path = data.get('path', '')
    position = data.get('position')

    if not root or not file_path or position is None:
        return jsonify({'error': 'Missing root, path, or position'}), 400

    save_position(current_user.username, root, file_path, float(position))
    return jsonify({'saved': True})


@bp.route('/api/playhead', methods=['GET'])
@login_required
def api_playhead_get():
    """Get saved playback position."""
    root = request.args.get('root', '')
    file_path = request.args.get('path', '')
    if not root or not file_path:
        return jsonify({'position': None})

    pos = get_position(current_user.username, root, file_path)
    return jsonify({'position': pos})


# --- Batch Operations ---


@bp.route('/api/batch/download', methods=['POST'])
@login_required
def api_batch_download():
    """Download multiple files as a ZIP archive."""
    data = request.get_json(silent=True) or {}
    files = data.get('files', [])

    if not files:
        return jsonify({'error': 'No files selected'}), 400
    if len(files) > 200:
        return jsonify({'error': 'Too many files (max 200)'}), 400

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            slug = f.get('root', '')
            rel_path = f.get('path', '')
            target = resolve_path_or_none(slug, rel_path)
            if target and target.exists() and target.is_file():
                arcname = f'{slug}/{rel_path}'
                zf.write(target, arcname)

    buffer.seek(0)
    log_action('download', current_user.username, f'batch {len(files)} files',
               ip=request.remote_addr)

    return send_file(
        buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='orrbit-download.zip',
    )


@bp.route('/api/batch/delete', methods=['POST'])
@login_required
def api_batch_delete():
    """Delete multiple files."""
    data = request.get_json(silent=True) or {}
    files = data.get('files', [])

    if not files:
        return jsonify({'error': 'No files selected'}), 400

    deleted = 0
    errors = []
    for f in files:
        slug = f.get('root', '')
        rel_path = f.get('path', '')
        target = resolve_path_or_none(slug, rel_path)
        if not target:
            errors.append(f'{slug}/{rel_path}: invalid path')
            continue
        if not target.exists():
            errors.append(f'{slug}/{rel_path}: not found')
            continue
        try:
            if target.is_file():
                target.unlink()
                deleted += 1
            elif target.is_dir():
                shutil.rmtree(target)
                deleted += 1
        except OSError as e:
            errors.append(f'{slug}/{rel_path}: {e}')

    if deleted:
        log_action('delete', current_user.username, f'batch {deleted} files',
                   ip=request.remote_addr)

    return jsonify({'deleted': deleted, 'errors': errors})


@bp.route('/api/batch/move', methods=['POST'])
@login_required
def api_batch_move():
    """Move multiple files to a destination directory."""
    data = request.get_json(silent=True) or {}
    files = data.get('files', [])
    dest_slug = data.get('dest_root', '')
    dest_path = data.get('dest_path', '')

    if not files or not dest_slug:
        return jsonify({'error': 'Missing files or destination'}), 400

    directory_map = current_app.config['DIRECTORY_MAP']
    if dest_slug not in directory_map:
        return jsonify({'error': 'Invalid destination root'}), 400

    dest_root = Path(directory_map[dest_slug])
    dest_dir = dest_root / dest_path if dest_path else dest_root

    try:
        dest_dir.resolve().relative_to(dest_root.resolve())
    except ValueError:
        return jsonify({'error': 'Invalid destination path'}), 403

    if not dest_dir.exists():
        return jsonify({'error': 'Destination directory does not exist'}), 404

    moved = 0
    errors = []
    for f in files:
        slug = f.get('root', '')
        rel_path = f.get('path', '')
        target = resolve_path_or_none(slug, rel_path)
        if not target or not target.exists():
            errors.append(f'{slug}/{rel_path}: not found')
            continue
        try:
            shutil.move(str(target), str(dest_dir / target.name))
            moved += 1
        except OSError as e:
            errors.append(f'{slug}/{rel_path}: {e}')

    if moved:
        log_action('move', current_user.username,
                   f'batch {moved} files to {dest_slug}/{dest_path}',
                   ip=request.remote_addr)

    return jsonify({'moved': moved, 'errors': errors})


# --- Activity Log ---

@bp.route('/activity')
@login_required
def activity_page():
    """Activity log page."""
    return render_template('activity.html')


@bp.route('/api/activity')
@login_required
def api_activity():
    """Activity log JSON API."""
    action = request.args.get('action', '')
    page = safe_int(request.args.get('page', 1), default=1, min_val=1)
    per_page = safe_int(request.args.get('per_page', 50), default=50, min_val=1, max_val=500)

    entries, total = get_activity(action=action, page=page, per_page=per_page)
    return jsonify({
        'entries': entries,
        'total': total,
        'page': page,
        'pages': (total + per_page - 1) // per_page if total else 0,
    })
