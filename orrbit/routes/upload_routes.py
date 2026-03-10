"""Upload routes for orrbit — staging area, direct upload, and share target."""

import os
import time
import json
import shutil
from pathlib import Path
from flask import (
    Blueprint, render_template, request, jsonify,
    abort, current_app, redirect, url_for,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from ..activity import log_action
from ..files import format_size

bp = Blueprint('upload', __name__)


def _staging_dir() -> Path:
    """Return the staging directory path, creating it if needed."""
    staging = Path(current_app.config['DATA_DIR']) / 'staging'
    staging.mkdir(parents=True, exist_ok=True)
    return staging


def _staging_meta_path(staging_dir: Path) -> Path:
    """Return path to staging metadata JSON file."""
    return staging_dir / '.meta.json'


def _load_meta(staging_dir: Path) -> dict:
    """Load staging metadata (upload info per file)."""
    meta_path = _staging_meta_path(staging_dir)
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_meta(staging_dir: Path, meta: dict):
    """Persist staging metadata."""
    meta_path = _staging_meta_path(staging_dir)
    meta_path.write_text(json.dumps(meta, indent=2))


def _unique_filename(staging_dir: Path, name: str) -> str:
    """Generate a unique filename to avoid collisions in staging."""
    safe = secure_filename(name) or 'upload'
    if not (staging_dir / safe).exists():
        return safe

    stem = Path(safe).stem
    suffix = Path(safe).suffix
    i = 1
    while (staging_dir / f'{stem}_{i}{suffix}').exists():
        i += 1
    return f'{stem}_{i}{suffix}'




# --- Web Share Target (POST from iOS/Android share sheet) ---

@bp.route('/upload/share', methods=['GET', 'POST'])
@login_required
def share_target():
    """Receive files from the OS share sheet (Web Share Target API).

    GET: redirect to staging (for browsers that navigate here).
    POST: save shared files to staging area.
    """
    if request.method == 'GET':
        return redirect(url_for('upload.staging_page'))

    files = request.files.getlist('file')
    if not files:
        return redirect(url_for('upload.staging_page'))

    staging = _staging_dir()
    meta = _load_meta(staging)

    for f in files:
        if f.filename:
            safe_name = _unique_filename(staging, f.filename)
            f.save(str(staging / safe_name))
            meta[safe_name] = {
                'original_name': f.filename,
                'uploaded_at': time.time(),
                'uploaded_by': current_user.id,
                'source': 'share_sheet',
            }

    _save_meta(staging, meta)
    return redirect(url_for('upload.staging_page'))


# --- Staging area ---

def _list_staging_files(staging: Path, meta: dict) -> list[dict]:
    """Build list of staged file info dicts."""
    files = []
    for entry in sorted(staging.iterdir()):
        if entry.name.startswith('.'):
            continue
        info = meta.get(entry.name, {})
        st = entry.stat()
        files.append({
            'name': entry.name,
            'original_name': info.get('original_name', entry.name),
            'size': st.st_size,
            'size_human': format_size(st.st_size),
            'uploaded_at': info.get('uploaded_at', st.st_mtime),
            'source': info.get('source', 'upload'),
        })
    return files


@bp.route('/staging')
@login_required
def staging_page():
    """Staging area page — view uploaded files pending organization."""
    staging = _staging_dir()
    meta = _load_meta(staging)
    directory_map = current_app.config['DIRECTORY_MAP']
    files = _list_staging_files(staging, meta)
    return render_template('staging.html', files=files, directories=directory_map)


@bp.route('/api/staging', methods=['GET'])
@login_required
def api_staging_list():
    """JSON list of staged files."""
    staging = _staging_dir()
    meta = _load_meta(staging)
    files = _list_staging_files(staging, meta)
    return jsonify({'files': files, 'total': len(files)})


@bp.route('/api/staging/move', methods=['POST'])
@login_required
def api_staging_move():
    """Move a staged file to a permanent directory."""
    data = request.get_json(silent=True) or {}
    filename = data.get('filename', '')
    dest_slug = data.get('slug', '')
    dest_path = data.get('path', '')  # subdirectory within the slug root

    if not filename or not dest_slug:
        return jsonify({'error': 'Missing filename or destination slug'}), 400

    # Validate destination
    directory_map = current_app.config['DIRECTORY_MAP']
    if dest_slug not in directory_map:
        return jsonify({'error': 'Unknown destination directory'}), 404

    dest_root = Path(directory_map[dest_slug])
    if dest_path:
        dest_dir = dest_root / dest_path
    else:
        dest_dir = dest_root

    # Prevent traversal
    try:
        dest_dir.resolve().relative_to(dest_root.resolve())
    except ValueError:
        return jsonify({'error': 'Invalid destination path'}), 403

    if not dest_dir.is_dir():
        return jsonify({'error': 'Destination directory does not exist'}), 404

    # Move file
    staging = _staging_dir()
    safe_name = secure_filename(filename)
    src = staging / safe_name
    if not src.exists() or not src.is_file():
        return jsonify({'error': 'File not found in staging'}), 404

    final_name = _unique_filename(dest_dir, safe_name)
    shutil.move(str(src), str(dest_dir / final_name))

    # Clean up metadata
    meta = _load_meta(staging)
    meta.pop(safe_name, None)
    _save_meta(staging, meta)

    return jsonify({
        'ok': True,
        'destination': f'{dest_slug}/{dest_path}/{final_name}'.strip('/'),
    })


@bp.route('/api/staging/delete', methods=['POST'])
@login_required
def api_staging_delete():
    """Delete a staged file."""
    data = request.get_json(silent=True) or {}
    filename = data.get('filename', '')

    if not filename:
        return jsonify({'error': 'Missing filename'}), 400

    staging = _staging_dir()
    safe_name = secure_filename(filename)
    target = staging / safe_name

    if not target.exists() or not target.is_file():
        return jsonify({'error': 'File not found'}), 404

    # Prevent traversal out of staging dir
    try:
        target.resolve().relative_to(staging.resolve())
    except ValueError:
        return jsonify({'error': 'Invalid filename'}), 403

    target.unlink()

    # Clean up metadata
    meta = _load_meta(staging)
    meta.pop(safe_name, None)
    _save_meta(staging, meta)

    return jsonify({'ok': True})


# --- Direct upload to directory or staging ---

@bp.route('/api/upload', methods=['POST'])
@bp.route('/api/upload/<slug>/', methods=['POST'])
@bp.route('/api/upload/<slug>/<path:rel_path>', methods=['POST'])
@login_required
def api_upload(slug=None, rel_path=''):
    """Upload files.

    Without slug: files go to staging.
    With slug/path: files go directly to that directory.
    """
    files = request.files.getlist('file')
    if not files or not files[0].filename:
        return jsonify({'error': 'No files provided'}), 400

    results = []

    if slug is None:
        # Upload to staging
        staging = _staging_dir()
        meta = _load_meta(staging)

        for f in files:
            if not f.filename:
                continue
            safe_name = _unique_filename(staging, f.filename)
            f.save(str(staging / safe_name))
            meta[safe_name] = {
                'original_name': f.filename,
                'uploaded_at': time.time(),
                'uploaded_by': current_user.id,
                'source': 'browser',
            }
            results.append({'name': safe_name, 'status': 'staged'})

        _save_meta(staging, meta)
    else:
        # Direct upload to directory
        directory_map = current_app.config['DIRECTORY_MAP']
        if slug not in directory_map:
            return jsonify({'error': 'Unknown directory'}), 404

        dest_root = Path(directory_map[slug])
        dest_dir = dest_root / rel_path if rel_path else dest_root

        # Prevent traversal
        try:
            dest_dir.resolve().relative_to(dest_root.resolve())
        except ValueError:
            return jsonify({'error': 'Invalid path'}), 403

        if not dest_dir.is_dir():
            return jsonify({'error': 'Directory not found'}), 404

        for f in files:
            if not f.filename:
                continue
            final_name = _unique_filename(dest_dir, f.filename)
            f.save(str(dest_dir / final_name))
            results.append({'name': final_name, 'status': 'uploaded'})

    if results:
        dest_desc = f'{slug}/{rel_path}' if slug else 'staging'
        log_action('upload', current_user.username,
                   f'{len(results)} file(s) to {dest_desc}',
                   ip=request.remote_addr)

    return jsonify({'ok': True, 'files': results})
