"""
Authentication for orrbit.

User management with bcrypt password hashing, JSON storage,
config-seeded users, and rate limiting.
"""

import json
import logging
import os
import time
import threading
from functools import wraps
from pathlib import Path
from flask import jsonify
from flask_login import UserMixin, current_user
import bcrypt

logger = logging.getLogger(__name__)

# Configured at init time
USERS_FILE: Path = None
_users_lock = threading.Lock()

# Rate limiting: {ip: [(timestamp, ...), ...]}
_fail_log: dict[str, list[float]] = {}
_fail_lock = threading.Lock()
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 300  # 5 minutes


def init_auth(data_dir: str, seed_users: list[dict] = None):
    """Initialize auth system with data directory and optional seed users."""
    global USERS_FILE
    USERS_FILE = Path(data_dir) / 'users.json'

    # Seed users on first boot (only if users.json doesn't exist)
    if not USERS_FILE.exists() and seed_users:
        users = {}
        for i, u in enumerate(seed_users, 1):
            username = u.get('username', '')
            password = u.get('password', '')
            if username and password:
                users[str(i)] = {
                    'username': username,
                    'password_hash': User.hash_password(password),
                    'is_admin': (i == 1),  # First user is admin
                }
        if users:
            save_users(users)
            logger.info("Seeded %d user(s) from config", len(users))


class User(UserMixin):
    """Flask-Login compatible User class."""

    def __init__(self, user_id: str, username: str, password_hash: str, is_admin: bool = False):
        self.id = user_id
        self.username = username
        self.password_hash = password_hash
        self.is_admin = is_admin

    def check_password(self, password: str) -> bool:
        """Verify password against stored hash."""
        return bcrypt.checkpw(
            password.encode('utf-8'),
            self.password_hash.encode('utf-8')
        )

    @staticmethod
    def hash_password(password: str) -> str:
        """Generate bcrypt hash for a password."""
        return bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')


def load_users() -> dict:
    """Load users from JSON file."""
    if not USERS_FILE or not USERS_FILE.exists():
        return {}
    try:
        with open(USERS_FILE, 'r') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def save_users(users: dict) -> None:
    """Save users to JSON file."""
    try:
        tmp = USERS_FILE.with_suffix('.tmp')
        with open(tmp, 'w') as f:
            json.dump(users, f, indent=2)
        os.replace(tmp, USERS_FILE)
    except OSError:
        with open(USERS_FILE, 'w') as f:
            json.dump(users, f, indent=2)


def get_user_by_id(user_id: str) -> User | None:
    """Load user by ID for Flask-Login."""
    users = load_users()
    if user_id in users:
        data = users[user_id]
        return User(user_id, data['username'], data['password_hash'],
                    is_admin=data.get('is_admin', False))
    return None


def get_user_by_username(username: str) -> User | None:
    """Load user by username for login."""
    users = load_users()
    for user_id, data in users.items():
        if data['username'] == username:
            return User(user_id, data['username'], data['password_hash'],
                        is_admin=data.get('is_admin', False))
    return None


def admin_required(f):
    """Decorator that requires the current user to be an admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated


def check_rate_limit(ip: str) -> bool:
    """Check if IP is rate-limited. Returns True if allowed."""
    now = time.time()
    with _fail_lock:
        if ip in _fail_log:
            # Prune old entries
            _fail_log[ip] = [t for t in _fail_log[ip] if now - t < RATE_LIMIT_WINDOW]
            if len(_fail_log[ip]) >= RATE_LIMIT_MAX:
                return False
    return True


def record_failure(ip: str):
    """Record a failed login attempt."""
    with _fail_lock:
        if ip not in _fail_log:
            _fail_log[ip] = []
        _fail_log[ip].append(time.time())
