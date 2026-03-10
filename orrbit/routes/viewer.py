"""Viewer routes for orrbit — file viewing, raw serving, thumbnails."""

from pathlib import Path
from flask import Blueprint, render_template, send_file, abort, redirect, url_for, request
from flask_login import login_required, current_user

from ..activity import log_action
from ..files import get_file_info, get_file_type, get_breadcrumbs, read_text_file, get_mime_type
from ..thumbnails import generate_thumbnail, get_video_metadata, format_duration
from ..indexer import query_index
from ..path_utils import resolve_path

bp = Blueprint('viewer', __name__)


@bp.route('/view/<slug>/<path:rel_path>')
@login_required
def view_file(slug, rel_path):
    """Media viewer — dispatches by file type."""
    abs_root, target = resolve_path(slug, rel_path)

    if not target.exists():
        abort(404)
    if target.is_dir():
        return redirect(url_for('browse.browse_directory', slug=slug, rel_path=rel_path))

    vault_path = Path(abs_root)
    info = get_file_info(target, vault_path)
    if not info:
        abort(404)

    breadcrumbs = get_breadcrumbs(rel_path)

    # Read text content for text files
    text_content = None
    if info.file_type == 'text':
        try:
            text_content = read_text_file(abs_root, rel_path)
        except Exception:
            text_content = '[Could not read file]'

    # Video metadata
    video_meta = {}
    if info.file_type == 'video':
        meta = get_video_metadata(target)
        video_meta = {
            'duration': format_duration(meta.get('duration')),
            'width': meta.get('width'),
            'height': meta.get('height'),
        }

    # Prev/next navigation within parent directory
    parent_dir = str(Path(rel_path).parent)
    if parent_dir == '.':
        parent_dir = ''

    entries, _ = query_index(
        root=slug,
        directory=parent_dir,
        sort_by='name',
        per_page=10000,
    )
    # Filter to files only
    files_in_dir = [e for e in entries if not e.is_dir]
    prev_file = None
    next_file = None
    for i, e in enumerate(files_in_dir):
        if e.path == rel_path:
            if i > 0:
                prev_file = files_in_dir[i - 1].path
            if i < len(files_in_dir) - 1:
                next_file = files_in_dir[i + 1].path
            break

    return render_template(
        'view.html',
        slug=slug,
        rel_path=rel_path,
        file=info,
        breadcrumbs=breadcrumbs,
        text_content=text_content,
        video_meta=video_meta,
        prev_file=prev_file,
        next_file=next_file,
    )


@bp.route('/raw/<slug>/<path:rel_path>')
@login_required
def raw_file(slug, rel_path):
    """Serve raw file with proper MIME type."""
    abs_root, target = resolve_path(slug, rel_path)

    if not target.exists() or target.is_dir():
        abort(404)

    mime = get_mime_type(target)

    # Log download
    if request.args.get('download') or 'download' in (request.headers.get('Sec-Fetch-Dest', '')):
        log_action('download', current_user.username, f'{slug}/{rel_path}',
                   ip=request.remote_addr)

    # Support range requests for video/audio streaming
    return send_file(
        target,
        mimetype=mime,
        conditional=True,
        download_name=target.name,
    )


@bp.route('/thumb/<slug>/<path:rel_path>')
@login_required
def thumb_file(slug, rel_path):
    """Generate and serve thumbnail."""
    abs_root, target = resolve_path(slug, rel_path)

    if not target.exists() or target.is_dir():
        abort(404)

    mime = get_mime_type(target)
    file_type = get_file_type(mime)

    thumb_path = generate_thumbnail(target, file_type, mime)
    if thumb_path and thumb_path.exists():
        return send_file(thumb_path, mimetype='image/jpeg')

    # No thumbnail — return 404 (client should show placeholder)
    abort(404)
