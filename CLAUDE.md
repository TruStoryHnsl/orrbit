# CLAUDE.md

This file provides guidance to AI assistants (Claude Code, Cursor, etc.) when working with code in this repository.

## What is Orrbit

Orrbit is a self-hosted cloud file server built with Flask. It serves files from configurable host directories ("roots") through a web UI with browsing, viewing, search, sharing, uploads, and an embedded SFTP server. It is a PWA with offline support.

## Development Commands

```bash
# Development server (auto-creates venv if needed)
./orrbit.sh dev
# Or manually:
.venv/bin/python3 run_dev.py

# Docker
docker compose up -d            # Start
docker compose build            # Rebuild
docker compose logs -f orrbit   # Logs

# Setup wizard — generates config.yaml and compose.yaml
python3 setup.py
```

There are no tests or linting configured — this is a hobby project that prioritizes iteration speed.

## Architecture

### App factory and config

`orrbit/__init__.py:create_app()` is the Flask application factory. It loads `config.yaml` (with `ORRBIT_*` env var overrides), initializes all subsystems, and registers blueprints.

Config is loaded by `orrbit/config.py:load_config()`. The `directories` map in config becomes `DIRECTORY_MAP` (slug → absolute path) — this is the central concept. Every file operation resolves through a slug + relative path.

### Data storage (dual model)

- **SQLite** (`data/orrbit_index.db`, WAL mode): file index (`files` table), share links (`share_links` table), activity log (`activity_log` table). All three subsystems share one DB file.
- **Per-user JSON** (`data/{favorites,tags,playhead}/<username>.json`): managed by `JsonStore` — a thread-safe JSON-file-per-user abstraction in `orrbit/json_store.py`. Favorites, tags, and playhead all follow this pattern.

### Route blueprints

| Blueprint | Prefix | Module |
|-----------|--------|--------|
| `auth` | `/login`, `/logout` | `routes/auth_routes.py` |
| `browse` | `/`, `/browse/`, `/api/list/`, `/api/search`, `/api/mkdir/` | `routes/browse.py` |
| `viewer` | `/view/`, `/raw/`, `/thumb/` | `routes/viewer.py` |
| `share` | `/api/share`, `/s/<token>` | `routes/share_routes.py` |
| `upload` | `/upload/share`, `/staging`, `/api/upload`, `/api/upload/chunked/`, `/api/staging/` | `routes/upload_routes.py` |
| `api` | `/api/favorites`, `/api/tags/`, `/api/playhead`, `/api/batch/`, `/activity` | `routes/api_routes.py` |
| `settings` | `/settings`, `/api/settings/` | `routes/settings_routes.py` |

All routes require `@login_required` except `/login` and `/s/<token>` (public share download).

### Path security

`orrbit/path_utils.py` provides `resolve_path(slug, rel_path)`, which validates the slug exists in `DIRECTORY_MAP` and prevents directory traversal via `Path.resolve().relative_to()`. **All route handlers that touch the filesystem must go through this.** There is no other path-handling code in the app.

### Background threads

- **Indexer** (`orrbit/indexer.py`): scans configured directories periodically using `os.walk()` / `os.scandir()`, maintains the SQLite index. Uses `gevent.get_hub().threadpool` to avoid blocking the event loop on slow NFS / CIFS I/O.
- **Share cleanup** (`orrbit/shares.py`): purges expired share links every 5 minutes.
- **Activity pruning** (`orrbit/activity.py`): optional, prunes log entries older than `activity.retention_days` every 6 hours.
- **SFTP server** (`orrbit/sftp.py`): optional embedded Paramiko SFTP server (default port 2222). Authenticates against Orrbit's user database and presents slugs as top-level directories.

### Gevent safety

**Critical**: any filesystem I/O targeting a remote mount (NFS / CIFS / SMB) MUST go through the gevent threadpool, not be called directly from a request handler. Direct `os.stat()` / `Path.exists()` / `os.listdir()` calls on stalled network paths will block gevent's event loop and freeze the entire app. See `_run_in_real_thread()` in `orrbit/indexer.py`.

The threadpool is configured in `gunicorn.conf.py:post_worker_init()`.

### Frontend

Server-rendered Jinja2 templates with vanilla JavaScript (no framework, no bundler). Each page has a paired JS file in `static/js/`. Templates extend `templates/base.html`. CSS is a single stylesheet (`static/css/style.css`) using CSS variables for theming (built-in themes via `[data-theme]` selectors, third-party via `static/themes/*.css`).

**Keyboard shortcuts** (`static/js/shortcuts.js`): `/` for search, `j`/`k` for item navigation, `Enter` to open, `Escape` to exit modes, `f` for favorite, `d` for download, `l`/`g` for list/grid view, `s` for select mode, arrow keys for prev/next in viewer.

### Key patterns

- Admin-only endpoints use the `@admin_required` decorator from `orrbit/auth.py`.
- Settings changes are applied in-memory AND persisted to `config.yaml` via `_write_raw_config()`.
- Thumbnails are generated on-demand via `ffmpeg` / `pdftoppm` and cached in `data/thumbs/` keyed by `md5(path + mtime)`. Dimensions are configurable and applied at runtime.
- The upload flow has a staging area (`data/staging/`) where files land before being moved to a permanent directory.
- Chunked uploads (`/api/upload/chunked/`) are used for large files (>50 MB). The client splits the file into 5 MB chunks, sends sequentially, and the server assembles them. Resumable via a status check.
- The Web Share Target endpoint (`/upload/share`) is CSRF-exempt because the OS share sheet cannot include a token.
- The text viewer has a raw/reflowed toggle via the `?raw=1` query parameter.
- `/api/settings` only returns the user list to admins (non-admins get an empty list).
- New directories can be created via Settings ("create if missing") or via the browse UI's "New Folder" button.

## Configuration

`config.yaml` controls everything. Key fields: `directories` (slug → path map), `users` (seeded on first boot), `indexer`, `thumbnails`, `sftp`, `activity`, `theme`. See `config.example.yaml` for defaults.

Environment overrides: `ORRBIT_APP_NAME`, `ORRBIT_PORT`, `ORRBIT_SECRET_KEY`, `ORRBIT_DATA_DIR`, `ORRBIT_CONFIG`.

## Production

Gunicorn with gevent worker (`gunicorn.conf.py`): single worker, no timeout (for long thumbnail generation). Docker image is based on `python:3.12-slim` with `ffmpeg`, `poppler-utils`, and `unrar-free`. Runs as root inside the container (standard for self-hosted apps — Docker namespace isolation protects the host).

Exposed ports: **5000** (HTTP), **2222** (SFTP). SFTP is disabled by default.
