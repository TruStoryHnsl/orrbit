"""Browse routes for orrbit — directory listing and API."""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app, abort
from flask_login import login_required

from ..indexer import query_index, scan_directory, search_all_roots
from ..thumbnails import get_directory_view_mode
from ..files import get_breadcrumbs
from ..path_utils import resolve_path, safe_int

bp = Blueprint('browse', __name__)


@bp.route('/')
@bp.route('/browse/')
@login_required
def index():
    """Root view — show configured directories as cards."""
    directory_map = current_app.config['DIRECTORY_MAP']
    return render_template('browse.html', is_root=True, directories=directory_map)


@bp.route('/browse/<slug>/')
@bp.route('/browse/<slug>/<path:rel_path>')
@login_required
def browse_directory(slug, rel_path=''):
    """Directory listing view."""
    abs_root, target = resolve_path(slug, rel_path)

    if not target.exists():
        abort(404)
    if not target.is_dir():
        # If it's a file, redirect to the viewer
        return redirect(url_for('viewer.view_file', slug=slug, rel_path=rel_path))

    breadcrumbs = get_breadcrumbs(rel_path)
    directory_map = current_app.config['DIRECTORY_MAP']
    view_mode = request.args.get('view', 'browse')

    return render_template(
        'browse.html',
        is_root=False,
        slug=slug,
        rel_path=rel_path,
        breadcrumbs=breadcrumbs,
        directory_name=slug,
        directories=directory_map,
        view_mode=view_mode,
    )


@bp.route('/api/list/<slug>/')
@bp.route('/api/list/<slug>/<path:rel_path>')
@login_required
def api_list(slug, rel_path=''):
    """JSON API for directory contents."""
    abs_root, target = resolve_path(slug, rel_path)

    if not target.exists() or not target.is_dir():
        return jsonify({'error': 'Not found'}), 404

    # Query params
    sort_by = request.args.get('sort', 'name')
    if sort_by not in ('name', 'size', 'date', 'type'):
        sort_by = 'name'
    sort_desc = request.args.get('desc', '0') == '1'
    file_type = request.args.get('type', '')
    search = request.args.get('q', '')
    page = safe_int(request.args.get('page', 1), default=1, min_val=1)
    per_page = safe_int(request.args.get('per_page', 100), default=100, min_val=1, max_val=500)

    entries, total = query_index(
        root=slug,
        directory=rel_path,
        query=search,
        file_type=file_type,
        sort_by=sort_by,
        sort_desc=sort_desc,
        page=page,
        per_page=per_page,
    )

    # If index is empty for this directory, trigger a scan
    if total == 0 and not search and not file_type:
        scan_directory(slug, abs_root, rel_path, max_depth=2)
        entries, total = query_index(
            root=slug,
            directory=rel_path,
            sort_by=sort_by,
            sort_desc=sort_desc,
            page=page,
            per_page=per_page,
        )

    view_mode = get_directory_view_mode(entries)

    return jsonify({
        'items': [e.to_display_dict() for e in entries],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page,
        'view_mode': view_mode,
        'slug': slug,
        'directory': rel_path,
    })


@bp.route('/api/search')
@login_required
def api_search():
    """Global search across all indexed directories."""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'items': [], 'total': 0, 'page': 1, 'pages': 0})

    sort_by = request.args.get('sort', 'name')
    if sort_by not in ('name', 'size', 'date', 'type'):
        sort_by = 'name'
    sort_desc = request.args.get('desc', '0') == '1'
    file_type = request.args.get('type', '')
    page = safe_int(request.args.get('page', 1), default=1, min_val=1)
    per_page = safe_int(request.args.get('per_page', 50), default=50, min_val=1, max_val=500)

    entries, total = search_all_roots(
        query=query,
        file_type=file_type,
        sort_by=sort_by,
        sort_desc=sort_desc,
        page=page,
        per_page=per_page,
    )

    return jsonify({
        'items': [e.to_display_dict() for e in entries],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page,
    })
