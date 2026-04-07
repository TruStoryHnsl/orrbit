"""
Embedded WebDAV server for orrbit.

Presents directory slugs as top-level folders, authenticated against
orrbit's user database.  Uses wsgidav for the WebDAV protocol layer
and cheroot as the WSGI server.

Architecture mirrors sftp.py: separate port, daemon thread, slug-based
virtual filesystem with path traversal protection.
"""

import logging
import os
import threading
import time
from io import BytesIO
from pathlib import Path

from wsgidav.dav_provider import DAVCollection, DAVNonCollection, DAVProvider
from wsgidav.dc.base_dc import BaseDomainController
from wsgidav.wsgidav_app import WsgiDAVApp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (mirrors sftp.py daemon-thread pattern)
# ---------------------------------------------------------------------------
_dav_running = False
_dav_thread: threading.Thread | None = None
_dav_server = None
_directory_map: dict[str, str] = {}
_read_only: bool = True
_port: int = 8080


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _resolve_dav_path(dav_path: str) -> tuple[str | None, Path | None]:
    """Resolve a WebDAV path to (slug, real_path).

    Returns (None, None) for the virtual root.
    Returns (slug, None) for a bare slug (the slug root itself).
    Returns (slug, Path) for a resolved sub-path.
    """
    clean = dav_path.strip('/')
    if not clean:
        return None, None

    parts = clean.split('/', 1)
    slug = parts[0]
    remainder = parts[1] if len(parts) > 1 else ''

    root = _directory_map.get(slug)
    if root is None:
        return None, None

    if not remainder:
        return slug, None

    root_path = Path(root)
    target = (root_path / remainder).resolve()

    # Path traversal guard
    try:
        target.relative_to(root_path.resolve())
    except ValueError:
        return None, None

    return slug, target


def _get_root_path(slug: str) -> Path | None:
    """Get the real filesystem path for a slug root."""
    root = _directory_map.get(slug)
    return Path(root) if root else None


# ---------------------------------------------------------------------------
# DAV Resources
# ---------------------------------------------------------------------------

class OrrbitRootCollection(DAVCollection):
    """Virtual root listing all slugs as directories."""

    def __init__(self, environ):
        super().__init__('/', environ)

    def get_display_name(self):
        return ''

    def get_member_names(self):
        return sorted(_directory_map.keys())

    def get_member(self, name):
        if name in _directory_map:
            return OrrbitSlugCollection(f'/{name}', environ=self.environ)
        return None

    def get_creation_date(self):
        return None

    def get_last_modified(self):
        return None


class OrrbitSlugCollection(DAVCollection):
    """A slug root directory mapped to a real filesystem path."""

    def __init__(self, path, environ):
        super().__init__(path, environ)
        slug = path.strip('/').split('/')[0]
        self._slug = slug
        self._real_path = Path(_directory_map[slug])

    def get_display_name(self):
        return self._slug

    def get_member_names(self):
        try:
            return sorted([
                e.name for e in self._real_path.iterdir()
                if not e.name.startswith('.')
            ])
        except OSError:
            return []

    def get_member(self, name):
        child = self._real_path / name
        if not child.exists() or name.startswith('.'):
            return None

        # Traversal guard
        try:
            child.resolve().relative_to(self._real_path.resolve())
        except ValueError:
            return None

        child_path = f'/{self._slug}/{name}'
        if child.is_dir():
            return OrrbitDirCollection(child_path, self.environ, child, self._slug)
        return OrrbitFileResource(child_path, self.environ, child, self._slug)

    def get_creation_date(self):
        try:
            return self._real_path.stat().st_ctime
        except OSError:
            return None

    def get_last_modified(self):
        try:
            return self._real_path.stat().st_mtime
        except OSError:
            return None

    def create_empty_resource(self, name):
        if _read_only:
            raise Exception('Read-only mode')
        child = self._real_path / name
        child.touch()
        child_path = f'/{self._slug}/{name}'
        return OrrbitFileResource(child_path, self.environ, child, self._slug)

    def create_collection(self, name):
        if _read_only:
            raise Exception('Read-only mode')
        child = self._real_path / name
        child.mkdir(parents=False, exist_ok=False)
        child_path = f'/{self._slug}/{name}'
        return OrrbitDirCollection(child_path, self.environ, child, self._slug)

    def delete(self):
        # Prevent deleting slug roots
        raise Exception('Cannot delete a root directory')

    def support_recursive_delete(self):
        return False


class _CrossRootError(Exception):
    """Raised when a WebDAV operation tries to cross slug root boundaries."""
    pass


class OrrbitDirCollection(DAVCollection):
    """A real directory inside a slug root."""

    def __init__(self, path, environ, real_path: Path, slug: str):
        super().__init__(path, environ)
        self._real_path = real_path
        self._slug = slug
        self._root_path = Path(_directory_map[slug])

    def get_display_name(self):
        return self._real_path.name

    def get_member_names(self):
        try:
            return sorted([
                e.name for e in self._real_path.iterdir()
                if not e.name.startswith('.')
            ])
        except OSError:
            return []

    def get_member(self, name):
        child = self._real_path / name
        if not child.exists() or name.startswith('.'):
            return None

        # Traversal guard
        try:
            child.resolve().relative_to(self._root_path.resolve())
        except ValueError:
            return None

        child_dav_path = self.path.rstrip('/') + '/' + name
        if child.is_dir():
            return OrrbitDirCollection(child_dav_path, self.environ, child, self._slug)
        return OrrbitFileResource(child_dav_path, self.environ, child, self._slug)

    def get_creation_date(self):
        try:
            return self._real_path.stat().st_ctime
        except OSError:
            return None

    def get_last_modified(self):
        try:
            return self._real_path.stat().st_mtime
        except OSError:
            return None

    def create_empty_resource(self, name):
        if _read_only:
            raise Exception('Read-only mode')
        child = self._real_path / name
        # Traversal guard
        try:
            child.resolve().relative_to(self._root_path.resolve())
        except ValueError:
            raise Exception('Invalid path')
        child.touch()
        child_dav_path = self.path.rstrip('/') + '/' + name
        return OrrbitFileResource(child_dav_path, self.environ, child, self._slug)

    def create_collection(self, name):
        if _read_only:
            raise Exception('Read-only mode')
        child = self._real_path / name
        # Traversal guard
        try:
            child.resolve().relative_to(self._root_path.resolve())
        except ValueError:
            raise Exception('Invalid path')
        child.mkdir(parents=False, exist_ok=False)
        child_dav_path = self.path.rstrip('/') + '/' + name
        return OrrbitDirCollection(child_dav_path, self.environ, child, self._slug)

    def delete(self):
        if _read_only:
            raise Exception('Read-only mode')
        import shutil
        shutil.rmtree(self._real_path)

    def support_recursive_delete(self):
        return not _read_only

    def handle_move(self, dest_path):
        if _read_only:
            raise Exception('Read-only mode')
        slug, dest_real = _resolve_dav_path(dest_path)
        if slug != self._slug or dest_real is None:
            raise Exception('Cannot move across roots')
        self._real_path.rename(dest_real)
        return True

    def handle_copy(self, dest_path, depth_infinity):
        if _read_only:
            raise Exception('Read-only mode')
        import shutil
        slug, dest_real = _resolve_dav_path(dest_path)
        if slug != self._slug or dest_real is None:
            raise _CrossRootError('Cannot copy across roots')
        shutil.copytree(str(self._real_path), str(dest_real))
        return True


class OrrbitFileResource(DAVNonCollection):
    """A real file inside a slug root."""

    def __init__(self, path, environ, real_path: Path, slug: str):
        super().__init__(path, environ)
        self._real_path = real_path
        self._slug = slug
        self._root_path = Path(_directory_map[slug])

    def get_display_name(self):
        return self._real_path.name

    def get_content_length(self):
        try:
            return self._real_path.stat().st_size
        except OSError:
            return 0

    def get_content_type(self):
        import mimetypes
        mime, _ = mimetypes.guess_type(str(self._real_path))
        return mime or 'application/octet-stream'

    def get_creation_date(self):
        try:
            return self._real_path.stat().st_ctime
        except OSError:
            return None

    def get_last_modified(self):
        try:
            return self._real_path.stat().st_mtime
        except OSError:
            return None

    def get_etag(self):
        try:
            st = self._real_path.stat()
            # wsgidav wraps in quotes itself, so return raw value
            return f'{st.st_mtime:.6f}-{st.st_size}'
        except OSError:
            return None

    def get_content(self):
        """Return file content as a file-like object."""
        try:
            _log_dav_action('webdav_download', self.environ, self._slug, self.path)
        except Exception:
            pass
        return open(self._real_path, 'rb')

    def begin_write(self, content_type=None):
        """Open file for writing and return a writable file-like object."""
        if _read_only:
            raise Exception('Read-only mode')
        try:
            _log_dav_action('webdav_upload', self.environ, self._slug, self.path)
        except Exception:
            pass
        return open(self._real_path, 'wb')

    def delete(self):
        if _read_only:
            raise Exception('Read-only mode')
        self._real_path.unlink()

    def handle_move(self, dest_path):
        if _read_only:
            raise Exception('Read-only mode')
        slug, dest_real = _resolve_dav_path(dest_path)
        if slug != self._slug or dest_real is None:
            raise Exception('Cannot move across roots')
        self._real_path.rename(dest_real)
        return True

    def handle_copy(self, dest_path, depth_infinity):
        if _read_only:
            raise Exception('Read-only mode')
        import shutil
        slug, dest_real = _resolve_dav_path(dest_path)
        if slug != self._slug or dest_real is None:
            raise _CrossRootError('Cannot copy across roots')
        shutil.copy2(str(self._real_path), str(dest_real))
        return True

    def support_etag(self):
        return True

    def support_ranges(self):
        return True


# ---------------------------------------------------------------------------
# DAV Provider
# ---------------------------------------------------------------------------

class OrrbitDAVProvider(DAVProvider):
    """Maps orrbit slugs as virtual top-level directories."""

    def __init__(self):
        super().__init__()

    def get_resource_inst(self, path, environ):
        """Return a DAVResource for the given path, or None."""
        clean = path.strip('/')

        # Virtual root
        if not clean:
            return OrrbitRootCollection(environ)

        parts = clean.split('/', 1)
        slug = parts[0]

        if slug not in _directory_map:
            return None

        root_path = Path(_directory_map[slug])

        # Bare slug → slug root collection
        if len(parts) == 1:
            return OrrbitSlugCollection(f'/{slug}', environ)

        # Sub-path
        remainder = parts[1]
        target = (root_path / remainder).resolve()

        # Path traversal guard
        try:
            target.relative_to(root_path.resolve())
        except ValueError:
            return None

        if not target.exists():
            return None

        dav_path = f'/{clean}'
        if target.is_dir():
            return OrrbitDirCollection(dav_path, environ, target, slug)
        return OrrbitFileResource(dav_path, environ, target, slug)

    def is_readonly(self):
        return _read_only


# ---------------------------------------------------------------------------
# Domain Controller (authentication)
# ---------------------------------------------------------------------------

class OrrbitDomainController(BaseDomainController):
    """Authenticate WebDAV requests against orrbit's user database."""

    def __init__(self, wsgidav_app, config):
        super().__init__(wsgidav_app, config)

    def get_domain_realm(self, path_info, environ):
        return 'orrbit'

    def require_authentication(self, realm, environ):
        return True

    def basic_auth_user(self, realm, user_name, password, environ):
        from .auth import get_user_by_username
        user = get_user_by_username(user_name)
        if user and user.check_password(password):
            environ['wsgidav.auth.user_name'] = user_name
            return True
        return False

    def supports_http_digest_auth(self):
        return False


# ---------------------------------------------------------------------------
# Activity logging
# ---------------------------------------------------------------------------

def _log_dav_action(action: str, environ: dict, slug: str, path: str):
    """Log a WebDAV action to the activity log."""
    try:
        from .activity import log_action
        username = environ.get('wsgidav.auth.user_name', 'unknown')
        log_action(action, username, f'{slug}:/{path.strip("/")}')
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Server thread management
# ---------------------------------------------------------------------------

def start_webdav_server(
    directory_map: dict[str, str],
    port: int = 8080,
    read_only: bool = True,
):
    """Start the embedded WebDAV server on a daemon thread."""
    global _dav_running, _dav_thread, _dav_server
    global _directory_map, _read_only, _port

    if _dav_running:
        return

    _directory_map = directory_map
    _read_only = read_only
    _port = port

    config = {
        'host': '0.0.0.0',
        'port': port,
        'provider_mapping': {'/': OrrbitDAVProvider()},
        'http_authenticator': {
            'domain_controller': OrrbitDomainController,
            'accept_basic': True,
            'accept_digest': False,
            'default_to_digest': False,
        },
        'verbose': 1,
        'logging': {
            'enable': True,
            'enable_loggers': [],
        },
        # Disable the built-in directory browser (we have our own UI)
        'dir_browser': {
            'enable': False,
        },
    }

    dav_app = WsgiDAVApp(config)

    def server_thread():
        global _dav_running, _dav_server
        _dav_running = True

        try:
            from cheroot.wsgi import Server as CherootServer
            _dav_server = CherootServer(
                ('0.0.0.0', port),
                dav_app,
            )
            _dav_server.shutdown_timeout = 1
            logger.info('WebDAV listening on port %d (read_only=%s)', port, read_only)
            _dav_server.start()
        except Exception as e:
            logger.error('WebDAV server error: %s', e)
        finally:
            _dav_running = False
            _dav_server = None

    _dav_thread = threading.Thread(target=server_thread, daemon=True)
    _dav_thread.start()


def stop_webdav_server():
    """Stop the WebDAV server."""
    global _dav_running, _dav_server
    if not _dav_running or not _dav_server:
        return
    _dav_running = False
    try:
        _dav_server.stop()
    except Exception:
        pass
    _dav_server = None
    logger.info('WebDAV server stopped')


def get_webdav_status() -> dict:
    """Get current WebDAV server status."""
    return {
        'running': _dav_running,
        'port': _port,
        'read_only': _read_only,
    }
