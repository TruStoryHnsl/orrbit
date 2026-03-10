"""Settings routes for orrbit — configuration management UI + API."""

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

import yaml
from flask import (
    Blueprint, current_app, jsonify, render_template, request,
)
from flask_login import current_user, login_required

from ..activity import log_action
from ..auth import User, load_users, save_users, admin_required
from ..config import slugify
from ..indexer import (
    build_index, get_indexer_status, start_background_indexer,
    stop_background_indexer,
)
from ..sftp import get_sftp_status, start_sftp_server, stop_sftp_server

bp = Blueprint('settings', __name__)

# Built-in themes: id -> {name, colors for swatch preview}
BUILTIN_THEMES = {
    'midnight': {
        'name': 'Midnight',
        'colors': ['#1a1a1a', '#242424', '#4a9eff', '#e0e0e0', '#333'],
    },
    'slate': {
        'name': 'Slate',
        'colors': ['#1b2129', '#232b35', '#5b9bd5', '#d4dae3', '#2e3a48'],
    },
    'oled': {
        'name': 'OLED',
        'colors': ['#000000', '#0a0a0a', '#4a9eff', '#e8e8e8', '#1a1a1a'],
    },
    'dawn': {
        'name': 'Dawn',
        'colors': ['#f5f5f5', '#ffffff', '#2563eb', '#1a1a1a', '#d5d5d5'],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config_path() -> Path:
    """Resolve the config.yaml path used at startup."""
    return Path(os.environ.get('ORRBIT_CONFIG', 'config.yaml'))


def _read_raw_config() -> dict:
    """Read the raw YAML config file."""
    p = _config_path()
    if p.exists():
        with open(p) as f:
            return yaml.safe_load(f) or {}
    return {}


def _write_raw_config(data: dict):
    """Atomic write of config dict back to YAML."""
    p = _config_path()
    tmp = p.with_suffix('.yaml.tmp')
    with open(tmp, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    os.replace(tmp, p)


def _error(msg: str, code: int = 400):
    return jsonify({'error': msg}), code


def _discover_themes() -> list[dict]:
    """Return list of all available themes (built-in + third-party)."""
    themes = []
    for tid, info in BUILTIN_THEMES.items():
        themes.append({
            'id': tid,
            'name': info['name'],
            'colors': info['colors'],
            'builtin': True,
        })

    # Scan static/themes/ for third-party CSS files
    themes_dir = Path(current_app.static_folder) / 'themes'
    if themes_dir.is_dir():
        for css_file in sorted(themes_dir.glob('*.css')):
            tid = css_file.stem
            if tid in BUILTIN_THEMES:
                continue
            # Try to read display name from first-line comment: /* Theme: Name */
            name = tid.replace('-', ' ').replace('_', ' ').title()
            try:
                first_line = css_file.read_text().split('\n', 1)[0]
                if first_line.startswith('/* Theme:') and '*/' in first_line:
                    name = first_line.split('Theme:', 1)[1].split('*/')[0].strip()
            except OSError:
                pass
            themes.append({
                'id': tid,
                'name': name,
                'colors': [],
                'builtin': False,
            })
    return themes


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@bp.route('/settings')
@login_required
def settings_page():
    return render_template('settings.html')


# ---------------------------------------------------------------------------
# GET current config
# ---------------------------------------------------------------------------

@bp.route('/api/settings')
@login_required
def get_settings():
    cfg = current_app.config
    users_raw = load_users()
    users_list = []
    for uid, u in users_raw.items():
        users_list.append({
            'id': uid,
            'username': u['username'],
            'is_current': uid == current_user.id,
        })

    dirs = []
    raw = _read_raw_config().get('directories', {})
    dir_map = cfg.get('DIRECTORY_MAP', {})
    for name, path in raw.items():
        slug = slugify(name)
        dirs.append({
            'name': name,
            'slug': slug,
            'path': path,
            'valid': slug in dir_map,
        })

    indexer = get_indexer_status()

    return jsonify({
        'general': {
            'app_name': cfg.get('APP_NAME', 'orrbit'),
            'tab_title': cfg.get('TAB_TITLE', ''),
            'tab_subtitle': cfg.get('TAB_SUBTITLE', True),
            'port': cfg.get('PORT', 5000),
            'max_upload_mb': cfg.get('MAX_CONTENT_LENGTH', 500 * 1024 * 1024) // (1024 * 1024),
            'data_dir': cfg.get('DATA_DIR', ''),
        },
        'directories': dirs,
        'users': users_list,
        'indexer': {
            'enabled': cfg.get('INDEXER', {}).get('enabled', True),
            'interval': cfg.get('INDEXER', {}).get('interval', 1800),
            'status': indexer,
        },
        'thumbnails': cfg.get('THUMBNAILS', {'enabled': True, 'width': 320, 'height': 180}),
        'sftp': {
            'enabled': cfg.get('SFTP', {}).get('enabled', False),
            'port': cfg.get('SFTP', {}).get('port', 2222),
            'read_only': cfg.get('SFTP', {}).get('read_only', True),
            'status': get_sftp_status(),
        },
        'theme': {
            'current': cfg.get('THEME', 'midnight'),
            'available': _discover_themes(),
        },
    })


# ---------------------------------------------------------------------------
# General settings
# ---------------------------------------------------------------------------

@bp.route('/api/settings/general', methods=['POST'])
@login_required
@admin_required
def update_general():
    data = request.get_json(silent=True) or {}
    raw = _read_raw_config()
    requires_restart = []

    if 'app_name' in data:
        name = str(data['app_name']).strip()
        if not name:
            return _error('App name cannot be empty')
        raw['app_name'] = name
        current_app.config['APP_NAME'] = name

    if 'tab_title' in data:
        title = str(data['tab_title']).strip()
        raw['tab_title'] = title
        current_app.config['TAB_TITLE'] = title

    if 'tab_subtitle' in data:
        sub = bool(data['tab_subtitle'])
        raw['tab_subtitle'] = sub
        current_app.config['TAB_SUBTITLE'] = sub

    if 'port' in data:
        try:
            port = int(data['port'])
            if port < 1 or port > 65535:
                raise ValueError
        except (ValueError, TypeError):
            return _error('Port must be 1-65535')
        if port != current_app.config.get('PORT'):
            raw['port'] = port
            requires_restart.append('port')

    if 'max_upload_mb' in data:
        try:
            mb = int(data['max_upload_mb'])
            if mb < 1:
                raise ValueError
        except (ValueError, TypeError):
            return _error('Max upload must be a positive integer')
        raw.setdefault('upload', {})['max_size_mb'] = mb
        current_app.config['MAX_CONTENT_LENGTH'] = mb * 1024 * 1024

    _write_raw_config(raw)
    log_action('settings', current_user.username, 'Updated general settings', request.remote_addr)
    return jsonify({'ok': True, 'requires_restart': requires_restart})


# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------

@bp.route('/api/settings/directories', methods=['POST'])
@login_required
@admin_required
def add_directory():
    data = request.get_json(silent=True) or {}
    name = str(data.get('name', '')).strip()
    path = str(data.get('path', '')).strip()

    if not name or not path:
        return _error('Name and path are required')

    abs_path = Path(path).resolve()
    if not abs_path.is_dir():
        return _error(f'Path does not exist or is not a directory: {path}')

    slug = slugify(name)
    if not slug:
        return _error('Name produces an invalid slug')

    dir_map = current_app.config['DIRECTORY_MAP']
    if slug in dir_map:
        return _error(f'Directory slug "{slug}" already exists')

    # Persist to YAML
    raw = _read_raw_config()
    raw.setdefault('directories', {})[name] = str(abs_path)
    _write_raw_config(raw)

    # Update in-memory
    dir_map[slug] = str(abs_path)

    # Kick off indexing in background
    threading.Thread(
        target=build_index, args=(slug, str(abs_path)),
        daemon=True,
    ).start()

    log_action('settings', current_user.username, f'Added directory: {name} -> {abs_path}', request.remote_addr)
    return jsonify({'ok': True, 'slug': slug})


@bp.route('/api/settings/directories/<slug>', methods=['DELETE'])
@login_required
@admin_required
def remove_directory(slug):
    dir_map = current_app.config['DIRECTORY_MAP']
    if slug not in dir_map:
        return _error('Directory not found', 404)

    # Remove from YAML (match by slug)
    raw = _read_raw_config()
    raw_dirs = raw.get('directories', {})
    keys_to_remove = [k for k in raw_dirs if slugify(k) == slug]
    for k in keys_to_remove:
        del raw_dirs[k]
    _write_raw_config(raw)

    # Remove from memory
    removed_path = dir_map.pop(slug, '')

    # Clean index entries for this root
    try:
        from ..indexer import get_connection, DB_LOCK
        with DB_LOCK:
            conn = get_connection()
            try:
                conn.execute("DELETE FROM files WHERE root = ?", (slug,))
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass

    log_action('settings', current_user.username, f'Removed directory: {slug} ({removed_path})', request.remote_addr)
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@bp.route('/api/settings/users', methods=['POST'])
@login_required
@admin_required
def add_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', ''))

    if not username or not password:
        return _error('Username and password are required')
    if len(password) < 4:
        return _error('Password must be at least 4 characters')

    users = load_users()

    # Check for duplicate username
    for u in users.values():
        if u['username'] == username:
            return _error(f'Username "{username}" already exists')

    # Generate next ID
    next_id = str(max((int(k) for k in users), default=0) + 1)
    users[next_id] = {
        'username': username,
        'password_hash': User.hash_password(password),
    }
    save_users(users)

    log_action('settings', current_user.username, f'Added user: {username}', request.remote_addr)
    return jsonify({'ok': True, 'user_id': next_id})


@bp.route('/api/settings/users/<user_id>', methods=['PUT'])
@login_required
@admin_required
def update_user(user_id):
    data = request.get_json(silent=True) or {}
    password = str(data.get('password', ''))

    if not password:
        return _error('Password is required')
    if len(password) < 4:
        return _error('Password must be at least 4 characters')

    users = load_users()
    if user_id not in users:
        return _error('User not found', 404)

    users[user_id]['password_hash'] = User.hash_password(password)
    save_users(users)

    log_action('settings', current_user.username,
               f'Changed password for: {users[user_id]["username"]}', request.remote_addr)
    return jsonify({'ok': True})


@bp.route('/api/settings/users/<user_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_user(user_id):
    users = load_users()
    if user_id not in users:
        return _error('User not found', 404)

    if user_id == current_user.id:
        return _error('Cannot delete yourself')

    if len(users) <= 1:
        return _error('Cannot delete the last user')

    username = users[user_id]['username']
    del users[user_id]
    save_users(users)

    log_action('settings', current_user.username, f'Deleted user: {username}', request.remote_addr)
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------

@bp.route('/api/settings/indexer', methods=['POST'])
@login_required
@admin_required
def update_indexer():
    data = request.get_json(silent=True) or {}
    raw = _read_raw_config()
    raw.setdefault('indexer', {})
    indexer_cfg = current_app.config.setdefault('INDEXER', {})

    if 'enabled' in data:
        enabled = bool(data['enabled'])
        raw['indexer']['enabled'] = enabled
        indexer_cfg['enabled'] = enabled

        if enabled:
            dir_map = current_app.config['DIRECTORY_MAP']
            interval = indexer_cfg.get('interval', 1800)
            if dir_map:
                start_background_indexer(dir_map, interval=interval)
        else:
            stop_background_indexer()

    if 'interval' in data:
        try:
            interval = int(data['interval'])
            if interval < 60:
                return _error('Interval must be at least 60 seconds')
        except (ValueError, TypeError):
            return _error('Interval must be a number')
        raw['indexer']['interval'] = interval
        indexer_cfg['interval'] = interval

    _write_raw_config(raw)
    log_action('settings', current_user.username, 'Updated indexer settings', request.remote_addr)
    return jsonify({'ok': True})


@bp.route('/api/settings/indexer/scan', methods=['POST'])
@login_required
@admin_required
def trigger_scan():
    dir_map = current_app.config.get('DIRECTORY_MAP', {})
    if not dir_map:
        return _error('No directories configured')

    def _scan():
        for slug, path in dir_map.items():
            try:
                build_index(slug, path)
            except Exception as e:
                logger.error("Scan error for %s: %s", slug, e)

    threading.Thread(target=_scan, daemon=True).start()
    log_action('settings', current_user.username, 'Triggered manual index scan', request.remote_addr)
    return jsonify({'ok': True, 'message': 'Scan started'})


# ---------------------------------------------------------------------------
# SFTP
# ---------------------------------------------------------------------------

@bp.route('/api/settings/sftp', methods=['POST'])
@login_required
@admin_required
def update_sftp():
    data = request.get_json(silent=True) or {}
    raw = _read_raw_config()
    raw.setdefault('sftp', {})
    sftp_cfg = current_app.config.setdefault('SFTP', {})

    if 'enabled' in data:
        raw['sftp']['enabled'] = bool(data['enabled'])
        sftp_cfg['enabled'] = bool(data['enabled'])

    if 'port' in data:
        try:
            port = int(data['port'])
            if port < 1 or port > 65535:
                raise ValueError
        except (ValueError, TypeError):
            return _error('Port must be 1-65535')
        raw['sftp']['port'] = port
        sftp_cfg['port'] = port

    if 'read_only' in data:
        raw['sftp']['read_only'] = bool(data['read_only'])
        sftp_cfg['read_only'] = bool(data['read_only'])

    _write_raw_config(raw)

    # Stop existing server, restart if enabled
    stop_sftp_server()
    if sftp_cfg.get('enabled', False):
        dir_map = current_app.config.get('DIRECTORY_MAP', {})
        if dir_map:
            start_sftp_server(
                dir_map,
                port=sftp_cfg.get('port', 2222),
                read_only=sftp_cfg.get('read_only', True),
                data_dir=current_app.config.get('DATA_DIR', './data'),
            )

    log_action('settings', current_user.username, 'Updated SFTP settings', request.remote_addr)
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Thumbnails
# ---------------------------------------------------------------------------

@bp.route('/api/settings/thumbnails', methods=['POST'])
@login_required
@admin_required
def update_thumbnails():
    data = request.get_json(silent=True) or {}
    raw = _read_raw_config()
    raw.setdefault('thumbnails', {})
    thumb_cfg = current_app.config.setdefault('THUMBNAILS', {})

    if 'enabled' in data:
        raw['thumbnails']['enabled'] = bool(data['enabled'])
        thumb_cfg['enabled'] = bool(data['enabled'])

    if 'width' in data:
        try:
            w = int(data['width'])
            if w < 50 or w > 2000:
                raise ValueError
        except (ValueError, TypeError):
            return _error('Width must be 50-2000')
        raw['thumbnails']['width'] = w
        thumb_cfg['width'] = w

    if 'height' in data:
        try:
            h = int(data['height'])
            if h < 50 or h > 2000:
                raise ValueError
        except (ValueError, TypeError):
            return _error('Height must be 50-2000')
        raw['thumbnails']['height'] = h
        thumb_cfg['height'] = h

    _write_raw_config(raw)
    log_action('settings', current_user.username, 'Updated thumbnail settings', request.remote_addr)
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

@bp.route('/api/settings/theme', methods=['POST'])
@login_required
@admin_required
def update_theme():
    data = request.get_json(silent=True) or {}
    theme_id = str(data.get('theme', '')).strip()

    if not theme_id:
        return _error('Theme ID is required')

    # Validate: must be a built-in or a third-party CSS file
    valid_ids = {t['id'] for t in _discover_themes()}
    if theme_id not in valid_ids:
        return _error(f'Unknown theme: {theme_id}')

    raw = _read_raw_config()
    raw['theme'] = theme_id
    _write_raw_config(raw)

    current_app.config['THEME'] = theme_id

    log_action('settings', current_user.username, f'Changed theme to: {theme_id}', request.remote_addr)
    return jsonify({'ok': True})
