"""
Orrbit configuration loader.

Reads config.yaml with environment variable overrides (ORRBIT_*).
"""

import logging
import os
import re
import secrets
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def slugify(name: str) -> str:
    """Convert a directory name to a URL-safe slug."""
    s = name.lower().strip()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_-]+', '-', s)
    return s.strip('-')


def load_config(path: str = None) -> dict:
    """Load configuration from YAML file with env var overrides.

    Precedence: env vars > YAML > defaults.
    """
    # Find config file
    if path is None:
        path = os.environ.get('ORRBIT_CONFIG', 'config.yaml')

    config_path = Path(path)
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    # Defaults
    defaults = {
        'app_name': 'orrbit',
        'tab_title': '',
        'tab_subtitle': False,
        'theme': 'midnight',
        'port': 5000,
        'secret_key': '',
        'data_dir': './data',
        'directories': {},
        'users': [],
        'indexer': {'interval': 1800, 'enabled': True},
        'thumbnails': {'enabled': True, 'width': 320, 'height': 180},
        'upload': {'max_size_mb': 500},
        'sftp': {'enabled': False, 'port': 2222, 'read_only': True},
    }

    # Merge defaults
    for key, default in defaults.items():
        if key not in config:
            config[key] = default
        elif isinstance(default, dict) and isinstance(config.get(key), dict):
            for k, v in default.items():
                if k not in config[key]:
                    config[key][k] = v

    # Environment variable overrides
    env_map = {
        'ORRBIT_APP_NAME': 'app_name',
        'ORRBIT_PORT': ('port', int),
        'ORRBIT_SECRET_KEY': 'secret_key',
        'ORRBIT_DATA_DIR': 'data_dir',
    }
    for env_var, target in env_map.items():
        val = os.environ.get(env_var)
        if val is not None:
            if isinstance(target, tuple):
                key, cast = target
                config[key] = cast(val)
            else:
                config[target] = val

    # Auto-generate secret_key if empty
    if not config['secret_key']:
        config['secret_key'] = secrets.token_hex(32)
        # Persist back to YAML so it survives restarts
        if config_path.exists():
            _persist_secret(config_path, config['secret_key'])

    # Resolve data_dir to absolute
    config['data_dir'] = str(Path(config['data_dir']).resolve())
    Path(config['data_dir']).mkdir(parents=True, exist_ok=True)

    # Build directory map: slug -> absolute path
    directory_map = {}
    raw_dirs = config.get('directories', {})
    if isinstance(raw_dirs, dict):
        for slug, dir_path in raw_dirs.items():
            safe_slug = slugify(slug)
            abs_path = Path(dir_path).resolve()
            if abs_path.is_dir():
                directory_map[safe_slug] = str(abs_path)
            else:
                logger.warning("Directory '%s' for slug '%s' does not exist, skipping", dir_path, safe_slug)
    config['directory_map'] = directory_map

    return config


def _persist_secret(config_path: Path, secret: str):
    """Write auto-generated secret_key back to config.yaml."""
    try:
        text = config_path.read_text()
        if 'secret_key:' in text:
            text = re.sub(
                r'(secret_key:\s*)(["\']?).*?\2',
                f'secret_key: "{secret}"',
                text,
                count=1,
            )
        else:
            text += f'\nsecret_key: "{secret}"\n'
        config_path.write_text(text)
    except OSError as e:
        logger.warning("Could not persist secret_key: %s", e)
