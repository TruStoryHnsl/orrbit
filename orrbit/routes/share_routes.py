"""Share link routes for orrbit — create, list, revoke, and public download."""

from pathlib import Path
from flask import Blueprint, request, jsonify, render_template, send_file, abort, current_app, url_for
from flask_login import login_required, current_user

from ..activity import log_action
from ..shares import create_share_link, get_share_link, list_share_links, revoke_share_link
from ..files import get_mime_type, format_size, get_file_type
from ..path_utils import resolve_path_or_none

bp = Blueprint('share', __name__)


def _resolve_shared_file(link) -> Path:
    """Resolve a share link to an absolute file path, or None."""
    target = resolve_path_or_none(link.root, link.file_path)
    if not target or not target.exists() or target.is_dir():
        return None
    return target


# --- Authenticated API ---

@bp.route('/api/share', methods=['POST'])
@login_required
def api_create_share():
    """Create a share link for a file."""
    data = request.get_json(silent=True) or {}
    slug = data.get('slug', '')
    file_path = data.get('path', '')
    ttl = data.get('ttl', 1800)

    if not slug or not file_path:
        return jsonify({'error': 'Missing slug or path'}), 400

    # Validate slug exists
    directory_map = current_app.config['DIRECTORY_MAP']
    if slug not in directory_map:
        return jsonify({'error': 'Unknown directory'}), 404

    # Validate file exists
    abs_root = Path(directory_map[slug])
    target = abs_root / file_path
    try:
        target.resolve().relative_to(abs_root.resolve())
    except ValueError:
        return jsonify({'error': 'Invalid path'}), 403

    if not target.exists() or target.is_dir():
        return jsonify({'error': 'File not found'}), 404

    # Clamp TTL: 1 minute to 24 hours
    ttl = max(60, min(86400, int(ttl)))

    link = create_share_link(
        root=slug,
        file_path=file_path,
        created_by=current_user.username,
        ttl=ttl,
    )

    share_url = url_for('share.public_download', token=link.token, _external=True)

    log_action('share', current_user.username, f'{slug}/{file_path}',
               ip=request.remote_addr)

    result = link.to_dict()
    result['url'] = share_url
    return jsonify(result), 201


@bp.route('/api/shares')
@login_required
def api_list_shares():
    """List active share links for the current user."""
    links = list_share_links(created_by=current_user.username)
    return jsonify({
        'links': [link.to_dict() for link in links],
        'total': len(links),
    })


@bp.route('/api/share/<token>', methods=['DELETE'])
@login_required
def api_revoke_share(token):
    """Revoke a share link."""
    # Only allow revoking own links (check ownership)
    link = get_share_link(token)
    if not link:
        return jsonify({'error': 'Link not found'}), 404
    if link.created_by != current_user.username:
        return jsonify({'error': 'Unauthorized'}), 403

    revoke_share_link(token)
    return jsonify({'ok': True})


# --- Share Management Page ---

@bp.route('/shares')
@login_required
def shares_page():
    """Share link management dashboard."""
    links = list_share_links(created_by=current_user.username)
    return render_template('shares.html', links=links)


# --- Public Routes (no auth) ---

@bp.route('/s/<token>')
def public_download(token):
    """Public share link preview/download page."""
    link = get_share_link(token)
    if not link or link.expired:
        return render_template('share_expired.html'), 404

    target = _resolve_shared_file(link)
    if not target:
        return render_template('share_expired.html'), 404

    # If ?download=1, serve the file directly
    if request.args.get('download') == '1':
        mime = get_mime_type(target)
        return send_file(target, mimetype=mime, as_attachment=True, download_name=target.name)

    # Otherwise show preview page
    stat = target.stat()
    size_human = format_size(stat.st_size)
    mime = get_mime_type(target)
    file_type = get_file_type(mime)

    return render_template('share_preview.html',
                           link=link,
                           filename=target.name,
                           size_human=size_human,
                           file_type=file_type,
                           token=token)
