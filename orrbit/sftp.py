"""
Embedded SFTP server for orrbit.

Presents directory slugs as top-level folders, authenticated against
orrbit's user database. Uses paramiko for the SSH/SFTP protocol layer.
"""

import base64
import hashlib
import logging
import os
import socket
import stat
import threading
import time
from pathlib import Path

import paramiko
from paramiko import (
    AUTH_FAILED,
    AUTH_SUCCESSFUL,
    OPEN_SUCCEEDED,
    SFTP_BAD_MESSAGE,
    SFTP_FAILURE,
    SFTP_NO_SUCH_FILE,
    SFTP_OK,
    SFTP_PERMISSION_DENIED,
    RSAKey,
    SFTPAttributes,
    SFTPHandle,
    SFTPServer,
    SFTPServerInterface,
    ServerInterface,
    Transport,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (mirrors indexer.py daemon-thread pattern)
# ---------------------------------------------------------------------------
_sftp_running = False
_sftp_thread: threading.Thread | None = None
_sftp_socket: socket.socket | None = None
_host_key: RSAKey | None = None
_directory_map: dict[str, str] = {}
_read_only: bool = True
_port: int = 2222


# ---------------------------------------------------------------------------
# Host key management
# ---------------------------------------------------------------------------

def _ensure_host_key(data_dir: str) -> RSAKey:
    """Load or generate the SFTP host key."""
    global _host_key
    key_path = Path(data_dir) / 'sftp_host_key'

    if key_path.exists():
        _host_key = RSAKey.from_private_key_file(str(key_path))
        logger.info('[sftp] Loaded host key from %s', key_path)
    else:
        _host_key = RSAKey.generate(3072)
        _host_key.write_private_key_file(str(key_path))
        os.chmod(str(key_path), 0o600)
        logger.info('[sftp] Generated new 3072-bit RSA host key → %s', key_path)

    return _host_key


def get_host_key_fingerprint() -> str:
    """Return SHA256 fingerprint of the host key, or empty string."""
    if _host_key is None:
        return ''
    raw = hashlib.sha256(_host_key.asbytes()).digest()
    return 'SHA256:' + base64.b64encode(raw).rstrip(b'=').decode('ascii')


# ---------------------------------------------------------------------------
# SSH server interface — authentication
# ---------------------------------------------------------------------------

class OrrbitSFTPServer(ServerInterface):
    """Paramiko ServerInterface that authenticates against orrbit users."""

    def __init__(self):
        self.username = ''
        super().__init__()

    def check_channel_request(self, kind, chanid):
        if kind == 'session':
            return OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def get_allowed_auths(self, username):
        return 'password'

    def check_auth_password(self, username, password):
        from .auth import get_user_by_username
        user = get_user_by_username(username)
        if user and user.check_password(password):
            self.username = username
            logger.info('[sftp] Login: %s', username)
            try:
                from .activity import log_action
                log_action('sftp_login', username, 'SFTP login')
            except Exception:
                pass
            return AUTH_SUCCESSFUL
        logger.warning('[sftp] Failed login attempt: %s', username)
        return AUTH_FAILED


# ---------------------------------------------------------------------------
# SFTP handle — wraps a Python file object
# ---------------------------------------------------------------------------

class OrrbitSFTPHandle(SFTPHandle):
    """Wraps a standard file object for read/write over SFTP."""

    def __init__(self, fobj, flags=0):
        super().__init__(flags)
        self._fobj = fobj

    def close(self):
        super().close()
        self._fobj.close()
        return SFTP_OK

    def read(self, offset, length):
        try:
            self._fobj.seek(offset)
            data = self._fobj.read(length)
            if data is None or len(data) == 0:
                return b''
            return data
        except Exception:
            return SFTP_FAILURE

    def write(self, offset, data):
        try:
            self._fobj.seek(offset)
            self._fobj.write(data)
            self._fobj.flush()
            return SFTP_OK
        except Exception:
            return SFTP_FAILURE

    def stat(self):
        try:
            st = os.fstat(self._fobj.fileno())
            return SFTPServer.convert_errno(0) if st is None else _stat_to_attr(st)
        except Exception:
            return SFTP_FAILURE


# ---------------------------------------------------------------------------
# SFTP filesystem interface — virtual root of slugs
# ---------------------------------------------------------------------------

def _stat_to_attr(st) -> SFTPAttributes:
    """Convert an os.stat_result to SFTPAttributes."""
    attr = SFTPAttributes()
    attr.st_size = st.st_size
    attr.st_uid = st.st_uid
    attr.st_gid = st.st_gid
    attr.st_mode = st.st_mode
    attr.st_atime = int(st.st_atime)
    attr.st_mtime = int(st.st_mtime)
    return attr


def _make_dir_attr(name: str, mtime: int = 0) -> SFTPAttributes:
    """Create SFTPAttributes for a virtual directory."""
    attr = SFTPAttributes()
    attr.st_mode = stat.S_IFDIR | 0o755
    attr.st_size = 0
    attr.st_uid = os.getuid()
    attr.st_gid = os.getgid()
    attr.st_atime = mtime or int(time.time())
    attr.st_mtime = mtime or int(time.time())
    attr.filename = name
    return attr


class OrrbitSFTPInterface(SFTPServerInterface):
    """Virtual SFTP filesystem mapping slugs → real directories."""

    def __init__(self, server, *args, **kwargs):
        self._username = getattr(server, 'username', 'unknown')
        super().__init__(server, *args, **kwargs)

    # --- Path resolution ---

    def _resolve(self, sftp_path: str) -> Path | None:
        """Resolve an SFTP path to a real filesystem path.

        Returns None if the path is invalid or escapes the root.
        """
        # Normalise: strip leading /, split
        clean = sftp_path.strip('/')
        if not clean:
            return None  # root itself is virtual

        parts = clean.split('/', 1)
        slug = parts[0]
        remainder = parts[1] if len(parts) > 1 else ''

        root = _directory_map.get(slug)
        if root is None:
            return None

        root_path = Path(root)
        target = (root_path / remainder).resolve()

        # Path traversal guard
        try:
            target.relative_to(root_path.resolve())
        except ValueError:
            return None

        return target

    def _slug_for_path(self, sftp_path: str) -> str | None:
        """Extract the slug from an SFTP path."""
        clean = sftp_path.strip('/')
        if not clean:
            return None
        return clean.split('/')[0]

    # --- Directory listing ---

    def list_folder(self, path):
        clean = path.strip('/')

        # Virtual root → list slugs
        if not clean:
            entries = []
            for slug in sorted(_directory_map):
                real = Path(_directory_map[slug])
                try:
                    st = real.stat()
                    attr = _make_dir_attr(slug, int(st.st_mtime))
                except OSError:
                    attr = _make_dir_attr(slug)
                entries.append(attr)
            return entries

        # Real directory
        real_path = self._resolve(path)
        if real_path is None or not real_path.is_dir():
            return SFTP_NO_SUCH_FILE

        entries = []
        try:
            for entry in real_path.iterdir():
                if entry.name.startswith('.'):
                    continue
                try:
                    st = entry.stat()
                    attr = _stat_to_attr(st)
                    attr.filename = entry.name
                    entries.append(attr)
                except OSError:
                    continue
        except OSError:
            return SFTP_FAILURE

        return entries

    # --- Stat ---

    def stat(self, path):
        return self._do_stat(path, follow_links=True)

    def lstat(self, path):
        return self._do_stat(path, follow_links=False)

    def _do_stat(self, path, follow_links=True):
        clean = path.strip('/')

        # Virtual root
        if not clean:
            return _make_dir_attr('/')

        # Check if it's a bare slug
        if '/' not in clean and clean in _directory_map:
            real = Path(_directory_map[clean])
            try:
                st = real.stat() if follow_links else real.lstat()
                attr = _stat_to_attr(st)
                attr.filename = clean
                return attr
            except OSError:
                return _make_dir_attr(clean)

        real_path = self._resolve(path)
        if real_path is None or not real_path.exists():
            return SFTP_NO_SUCH_FILE

        try:
            st = real_path.stat() if follow_links else real_path.lstat()
            attr = _stat_to_attr(st)
            attr.filename = real_path.name
            return attr
        except OSError:
            return SFTP_FAILURE

    # --- File open ---

    def open(self, path, flags, attr):
        real_path = self._resolve(path)
        if real_path is None:
            return SFTP_NO_SUCH_FILE

        # Determine read/write mode
        writing = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))

        if writing and _read_only:
            return SFTP_PERMISSION_DENIED

        try:
            if writing:
                if flags & os.O_APPEND:
                    mode = 'ab+'
                elif flags & os.O_TRUNC:
                    mode = 'wb+'
                elif flags & os.O_CREAT:
                    mode = 'wb+' if not real_path.exists() else 'rb+'
                else:
                    mode = 'rb+'
                fobj = open(real_path, mode)
                # Log write access
                try:
                    slug = self._slug_for_path(path)
                    from .activity import log_action
                    log_action('sftp_upload', self._username,
                               f'{slug}:/{path.strip("/")}')
                except Exception:
                    pass
            else:
                if not real_path.exists():
                    return SFTP_NO_SUCH_FILE
                fobj = open(real_path, 'rb')
                # Log download
                try:
                    slug = self._slug_for_path(path)
                    from .activity import log_action
                    log_action('sftp_download', self._username,
                               f'{slug}:/{path.strip("/")}')
                except Exception:
                    pass
        except PermissionError:
            return SFTP_PERMISSION_DENIED
        except FileNotFoundError:
            return SFTP_NO_SUCH_FILE
        except OSError:
            return SFTP_FAILURE

        return OrrbitSFTPHandle(fobj, flags)

    # --- Write operations (guarded by read_only) ---

    def remove(self, path):
        if _read_only:
            return SFTP_PERMISSION_DENIED
        real_path = self._resolve(path)
        if real_path is None or not real_path.exists():
            return SFTP_NO_SUCH_FILE
        try:
            real_path.unlink()
            return SFTP_OK
        except OSError:
            return SFTP_FAILURE

    def rename(self, oldpath, newpath):
        if _read_only:
            return SFTP_PERMISSION_DENIED

        old_real = self._resolve(oldpath)
        new_real = self._resolve(newpath)
        if old_real is None or new_real is None:
            return SFTP_NO_SUCH_FILE
        if not old_real.exists():
            return SFTP_NO_SUCH_FILE

        # Must be within the same slug root
        old_slug = self._slug_for_path(oldpath)
        new_slug = self._slug_for_path(newpath)
        if old_slug != new_slug:
            return SFTP_PERMISSION_DENIED

        try:
            old_real.rename(new_real)
            return SFTP_OK
        except OSError:
            return SFTP_FAILURE

    def mkdir(self, path, attr):
        if _read_only:
            return SFTP_PERMISSION_DENIED
        real_path = self._resolve(path)
        if real_path is None:
            return SFTP_NO_SUCH_FILE
        try:
            real_path.mkdir(parents=False, exist_ok=False)
            return SFTP_OK
        except FileExistsError:
            return SFTP_FAILURE
        except OSError:
            return SFTP_FAILURE

    def rmdir(self, path):
        if _read_only:
            return SFTP_PERMISSION_DENIED
        # Don't allow removing slug roots
        clean = path.strip('/')
        if clean in _directory_map:
            return SFTP_PERMISSION_DENIED
        real_path = self._resolve(path)
        if real_path is None or not real_path.is_dir():
            return SFTP_NO_SUCH_FILE
        try:
            real_path.rmdir()
            return SFTP_OK
        except OSError:
            return SFTP_FAILURE


# ---------------------------------------------------------------------------
# Connection handler
# ---------------------------------------------------------------------------

def _handle_connection(client_sock, addr):
    """Handle a single SFTP client connection."""
    transport = None
    try:
        transport = Transport(client_sock)
        transport.add_server_key(_host_key)

        server = OrrbitSFTPServer()
        transport.set_subsystem_handler(
            'sftp', SFTPServer, OrrbitSFTPInterface,
        )

        transport.start_server(server=server)

        # Wait for the client to finish (channel close / disconnect)
        channel = transport.accept(timeout=60)
        if channel is None:
            logger.debug('[sftp] No channel opened by %s', addr)
            return

        # Keep alive until channel closes
        while transport.is_active():
            time.sleep(1)

    except Exception as e:
        logger.debug('[sftp] Connection error from %s: %s', addr, e)
    finally:
        if transport:
            try:
                transport.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Thread management (mirrors indexer.py pattern)
# ---------------------------------------------------------------------------

def start_sftp_server(
    directory_map: dict[str, str],
    port: int = 2222,
    read_only: bool = True,
    data_dir: str = './data',
):
    """Start the embedded SFTP server on a daemon thread."""
    global _sftp_running, _sftp_thread, _sftp_socket
    global _directory_map, _read_only, _port

    if _sftp_running:
        return

    _directory_map = directory_map
    _read_only = read_only
    _port = port

    _ensure_host_key(data_dir)

    def accept_loop():
        global _sftp_running, _sftp_socket
        _sftp_running = True

        try:
            _sftp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _sftp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            _sftp_socket.settimeout(2.0)
            _sftp_socket.bind(('0.0.0.0', port))
            _sftp_socket.listen(10)
            logger.info('Listening on port %d (read_only=%s)', port, read_only)
        except OSError as e:
            logger.error('Failed to bind port %d: %s', port, e)
            _sftp_running = False
            return

        while _sftp_running:
            try:
                client_sock, addr = _sftp_socket.accept()
                logger.info('[sftp] Connection from %s', addr)
                t = threading.Thread(
                    target=_handle_connection,
                    args=(client_sock, addr),
                    daemon=True,
                )
                t.start()
            except socket.timeout:
                continue
            except OSError:
                if _sftp_running:
                    logger.debug('[sftp] Accept error')
                break

        # Cleanup
        try:
            if _sftp_socket:
                _sftp_socket.close()
        except Exception:
            pass
        _sftp_socket = None
        logger.info('Server stopped')

    _sftp_thread = threading.Thread(target=accept_loop, daemon=True)
    _sftp_thread.start()


def stop_sftp_server():
    """Stop the SFTP server."""
    global _sftp_running, _sftp_socket
    if not _sftp_running:
        return
    _sftp_running = False
    # Close the listening socket to break accept()
    if _sftp_socket:
        try:
            _sftp_socket.close()
        except Exception:
            pass
    logger.info('Stopping...')


def get_sftp_status() -> dict:
    """Get current SFTP server status."""
    return {
        'running': _sftp_running,
        'port': _port,
        'read_only': _read_only,
        'host_key_fingerprint': get_host_key_fingerprint(),
    }
