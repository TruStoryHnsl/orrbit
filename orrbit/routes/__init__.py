"""Route registration for orrbit."""

from .auth_routes import bp as auth_bp
from .browse import bp as browse_bp
from .viewer import bp as viewer_bp
from .share_routes import bp as share_bp
from .upload_routes import bp as upload_bp
from .api_routes import bp as api_bp
from .settings_routes import bp as settings_bp


def register_routes(app):
    """Register all route blueprints."""
    app.register_blueprint(auth_bp)
    app.register_blueprint(browse_bp)
    app.register_blueprint(viewer_bp)
    app.register_blueprint(share_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(settings_bp)
