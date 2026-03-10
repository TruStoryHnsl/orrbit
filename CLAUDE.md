# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Orrbit

Orrbit is a self-hosted cloud file server built with Flask. It serves files from configurable host directories ("roots") through a web UI with browsing, viewing, search, sharing, uploads, and an embedded SFTP server. It is a PWA with offline support.

## Development Commands

```bash
# Development server (auto-creates venv if needed)
./orrbit.sh dev
# Or manually:
.venv/bin/python3 run_dev.py

# Docker
docker compose up -d          # Start
docker compose build           # Rebuild
docker compose logs -f orrbit  # Logs

# Setup wizard (generates config.yaml, compose.yaml, optional nginx/VPS)
python3 setup.py
```

There are no tests or linting configured.

## Architecture

### App Factory & Config

`orrbit/__init__.py:create_app()` is the Flask application factory. It loads `config.yaml` (with `ORRBIT_*` env var overrides), initializes all subsystems, and registers blueprints.

Config is loaded by `orrbit/config.py:load_config()`. The `directories` map in config becomes `DIRECTORY_MAP` (slug → absolute path) — this is the central concept. Every file operation resolves through a slug + relative path.

### Data Storage (Dual Model)

- **SQLite** (`data/orrbit_index.db`, WAL mode): file index (`files` table), share links (`share_links` table), activity log (`activity_log` table). All three subsystems share one DB file.
- **Per-user JSON** (`data/{favorites,tags,playhead}/<username>.json`): managed by `JsonStore` — a thread-safe JSON-file-per-user abstraction in `orrbit/json_store.py`. Favorites, tags, and playhead all follow this pattern.

### Route Blueprints

| Blueprint | Prefix | Module |
|-----------|--------|--------|
| `auth` | `/login`, `/logout` | `routes/auth_routes.py` |
| `browse` | `/`, `/browse/`, `/api/list/`, `/api/search` | `routes/browse.py` |
| `viewer` | `/view/`, `/raw/`, `/thumb/` | `routes/viewer.py` |
| `share` | `/api/share`, `/s/<token>` | `routes/share_routes.py` |
| `upload` | `/upload/share`, `/staging`, `/api/upload`, `/api/staging/` | `routes/upload_routes.py` |
| `api` | `/api/favorites`, `/api/tags/`, `/api/playhead`, `/api/batch/`, `/activity` | `routes/api_routes.py` |
| `settings` | `/settings`, `/api/settings/` | `routes/settings_routes.py` |

All routes require `@login_required` except `/login` and `/s/<token>` (public share download).

### Path Security

`orrbit/path_utils.py` provides `resolve_path(slug, rel_path)` which validates the slug exists in `DIRECTORY_MAP` and prevents directory traversal via `Path.resolve().relative_to()`. All route handlers that touch the filesystem must go through this.

### Background Threads

- **Indexer** (`orrbit/indexer.py`): scans configured directories periodically using `os.walk()`/`os.scandir()`, maintains the SQLite index. Uses `gevent.get_hub().threadpool` to avoid blocking the event loop on NFS I/O.
- **Share cleanup** (`orrbit/shares.py`): purges expired share links every 5 minutes.
- **SFTP server** (`orrbit/sftp.py`): optional embedded Paramiko SFTP server on port 2222, authenticates against orrbit's user database, presents slugs as top-level directories.

### Frontend

Server-rendered Jinja2 templates with vanilla JS (no framework). Each page has a paired JS file in `static/js/`. Templates extend `templates/base.html`. CSS is in `static/css/style.css` with theme support (built-in themes via `[data-theme]` selectors, third-party via `static/themes/*.css`).

### Key Patterns

- Admin-only endpoints use `@admin_required` decorator from `orrbit/auth.py`
- Settings changes are applied in-memory AND persisted to `config.yaml` via `_write_raw_config()`
- Thumbnails are generated on-demand via ffmpeg/pdftoppm and cached in `data/thumbs/` keyed by md5(path+mtime)
- The upload flow has a staging area (`data/staging/`) where files land before being moved to a permanent directory
- The `Web Share Target API` endpoint (`/upload/share`) is CSRF-exempt since the OS share sheet can't include tokens

## Configuration

`config.yaml` controls everything. Key fields: `directories` (slug→path map), `users` (seeded on first boot), `indexer`, `thumbnails`, `sftp`, `theme`. See `config.example.yaml` for defaults. Environment overrides: `ORRBIT_APP_NAME`, `ORRBIT_PORT`, `ORRBIT_SECRET_KEY`, `ORRBIT_DATA_DIR`, `ORRBIT_CONFIG`.

## Production

Gunicorn with gevent worker (`gunicorn.conf.py`): single worker, no timeout (for long thumbnail generation). Docker image based on python:3.12-slim with ffmpeg and poppler-utils. Runs as uid 3000/gid 4500.
