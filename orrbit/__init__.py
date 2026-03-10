"""
Orrbit — Cloud file server.

Application factory.
"""

import logging
import os
from datetime import timedelta
from pathlib import Path
from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

from .config import load_config


def create_app(config_path: str = None) -> Flask:
    """Create and configure the Flask application."""
    config = load_config(config_path)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # Create Flask app with correct template/static paths
    app_dir = Path(__file__).parent.parent
    app = Flask(
        __name__,
        template_folder=str(app_dir / 'templates'),
        static_folder=str(app_dir / 'static'),
    )

    # Flask config
    app.config['SECRET_KEY'] = config['secret_key']
    app.config['APP_NAME'] = config['app_name']
    app.config['PORT'] = config['port']
    app.config['DATA_DIR'] = config['data_dir']
    app.config['DIRECTORY_MAP'] = config['directory_map']
    app.config['INDEXER'] = config['indexer']
    app.config['THUMBNAILS'] = config['thumbnails']
    app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=30)
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
    app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['REMEMBER_COOKIE_SAMESITE'] = 'Strict'
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True
    app.config['MAX_CONTENT_LENGTH'] = config['upload']['max_size_mb'] * 1024 * 1024
    app.config['TAB_TITLE'] = config.get('tab_title', '')
    app.config['TAB_SUBTITLE'] = config.get('tab_subtitle', True)
    app.config['THEME'] = config.get('theme', 'midnight')
    app.config['SFTP'] = config.get('sftp', {'enabled': False, 'port': 2222, 'read_only': True})

    # CSRF protection
    csrf = CSRFProtect(app)

    # Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = None

    from .auth import get_user_by_id, init_auth

    @login_manager.user_loader
    def load_user(user_id):
        return get_user_by_id(user_id)

    # Initialize auth (seed users on first boot)
    init_auth(config['data_dir'], config.get('users', []))

    # Initialize thumbnails
    if config['thumbnails']['enabled']:
        from .thumbnails import init_thumb_cache
        init_thumb_cache(config['data_dir'])

    # Initialize indexer DB + shares DB
    from .indexer import init_db, start_background_indexer
    init_db(config['data_dir'])

    from .shares import init_shares_db, start_cleanup_thread
    init_shares_db(config['data_dir'])

    # Initialize Phase 5 modules
    from .favorites import init_favorites
    from .tags import init_tags
    from .playhead import init_playhead
    from .activity import init_activity_db
    init_favorites(config['data_dir'])
    init_tags(config['data_dir'])
    init_playhead(config['data_dir'])
    init_activity_db(config['data_dir'])

    # Skip background services in the reloader parent process.
    # Flask debug mode spawns two processes: a parent (file watcher) and a child
    # (actual server). WERKZEUG_RUN_MAIN is set in the child. Without this guard,
    # both processes try to bind SFTP/indexer, causing port conflicts.
    import os
    _is_reloader_parent = os.environ.get('FLASK_DEBUG') == '1' and not os.environ.get('WERKZEUG_RUN_MAIN')

    # Start share cleanup thread
    if not _is_reloader_parent:
        start_cleanup_thread()

    # Start background indexer
    if config['indexer']['enabled'] and config['directory_map'] and not _is_reloader_parent:
        start_background_indexer(
            config['directory_map'],
            interval=config['indexer']['interval'],
        )

    # Start SFTP server
    sftp_cfg = config.get('sftp', {})
    if sftp_cfg.get('enabled', False) and config['directory_map'] and not _is_reloader_parent:
        from .sftp import start_sftp_server
        start_sftp_server(
            config['directory_map'],
            port=sftp_cfg.get('port', 2222),
            read_only=sftp_cfg.get('read_only', True),
            data_dir=config['data_dir'],
        )

    # Register routes
    from .routes import register_routes
    register_routes(app)

    # Exempt the Web Share Target from CSRF — the OS share sheet cannot
    # include a CSRF token, so this endpoint must be exempted.
    csrf.exempt('upload.share_target')

    # Error handlers — JSON for API paths, HTML for page paths
    from flask import jsonify as _jsonify, render_template as _render

    error_messages = {
        400: 'Bad Request',
        401: 'Unauthorized',
        403: 'Forbidden',
        404: 'Not Found',
        500: 'Internal Server Error',
    }

    def _handle_error(e):
        code = getattr(e, 'code', 500)
        msg = error_messages.get(code, 'Error')
        from flask import request as _req
        if _req.path.startswith('/api/'):
            return _jsonify({'error': msg}), code
        return _render('error.html', error_code=code, error_message=msg), code

    for code in error_messages:
        app.register_error_handler(code, _handle_error)

    # Serve service worker from root scope (must be at / for scope)
    @app.route('/service-worker.js')
    def service_worker():
        from flask import send_from_directory
        return send_from_directory(
            app.static_folder, 'service-worker.js',
            mimetype='application/javascript',
            max_age=0,
        )

    # Dynamic manifest with configured app name
    @app.route('/manifest.json')
    def manifest():
        from flask import jsonify as _j
        return _j({
            'name': app.config['APP_NAME'],
            'short_name': app.config['APP_NAME'],
            'description': 'Cloud file server',
            'start_url': '/browse/',
            'display': 'standalone',
            'background_color': '#1a1a1a',
            'theme_color': '#1a1a1a',
            'icons': [
                {'src': '/static/icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                {'src': '/static/icons/icon-512.png', 'sizes': '512x512', 'type': 'image/png'},
            ],
            'share_target': {
                'action': '/upload/share',
                'method': 'POST',
                'enctype': 'multipart/form-data',
                'params': {
                    'files': [{'name': 'file', 'accept': ['*/*']}]
                }
            }
        })

    # Context processor for templates
    @app.context_processor
    def inject_globals():
        return {
            'app_name': app.config['APP_NAME'],
            'tab_title': app.config.get('TAB_TITLE', ''),
            'tab_subtitle': app.config.get('TAB_SUBTITLE', True),
            'theme': app.config.get('THEME', 'midnight'),
            'directory_map': app.config['DIRECTORY_MAP'],
        }

    # Security headers
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if 'Content-Security-Policy' not in response.headers:
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; "
                "img-src 'self' data: blob:; "
                "media-src 'self' blob:; "
                "worker-src 'self' blob:;"
            )
        return response

    return app
