# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Orrbit

Orrbit is a self-hosted cloud file server built with Flask. It serves files from configurable host directories ("roots") through a web UI with browsing, viewing, search, sharing, uploads, and an embedded SFTP server. It is a PWA with offline support.

Currently deployed on **orrgate** as the web interface for the **orrigins NAS** at `orrigins.com`. This is a bespoke deployment — the app is generalized for public release but the deployment is tailored to this network.

## Network Context

Orrbit is part of a multi-machine homelab network:

| Machine | Role | Relevant to Orrbit |
|---------|------|--------------------|
| **orrgate** | Hub — runs orrbit, orrapus, services | Hosts orrbit dev server, serves orrigins.com |
| **orrion** | GPU compute, ComfyUI | Development work happens here via Claude Code over SSH |
| **orrpheus** | MacBook M1 Pro | Alternate dev environment |
| **orrigins** | Synology NAS (192.168.1.123) | Primary data source — mounted at /mnt/vault via CIFS |

## Deployment & Update Pipeline

### Source of Truth

- **GitHub**: `git@github.com:TruStoryHnsl/orrbit.git` (public repo)
- **Working copy**: `orrgate:/docker/stacks/orrbit/`

### Update Workflow

```
Any machine (dev)  ->  git commit  ->  git push  ->  GitHub
                                                       |
orrgate (production)  <-  git pull  <------------------+
```

1. **Edit code** on any machine with a clone of the repo
2. **Test locally** using the dev server: `.venv/bin/python3 run_dev.py`
3. **Commit and push**: `git commit && git push origin main`
4. **Deploy on orrgate**: `cd /docker/stacks/orrbit && git pull` (auto-reloads in dev mode)

For dev mode (current deployment), Flask auto-reloads on code changes — no restart needed after `git pull` unless gunicorn.conf.py or startup code changed.

### SSH Access Between Machines

| From | To | Command | Auth |
|------|----|---------|------|
| orrion | orrgate | `ssh orrgate` | SSH key (ed25519) |
| orrion | orrpheus | `ssh coltonorr@192.168.1.132` | SSH key |
| orrgate | GitHub | `git push` | SSH key (ed25519, added to GitHub) |

### Development Server

```bash
cd /docker/stacks/orrbit
.venv/bin/python3 run_dev.py    # port 5001, debug mode, auto-reload
```

Port 5000 is taken by orrapus on orrgate. Orrbit dev runs on **5001**.

### Production (Docker)

```bash
cd /docker/stacks/orrbit
docker compose up -d            # builds from local Dockerfile
docker compose build             # rebuild after code changes
docker compose logs -f orrbit    # tail logs
```

Docker binds to port 5000 internally — update compose.yaml port mapping to avoid conflicts with orrapus.

## Architecture

### App Factory & Config

`orrbit/__init__.py:create_app()` is the Flask application factory. It loads `config.yaml` (with `ORRBIT_*` env var overrides), initializes all subsystems, and registers blueprints.

Config is loaded by `orrbit/config.py:load_config()`. The `directories` map in config becomes `DIRECTORY_MAP` (slug -> absolute path) — this is the central concept. Every file operation resolves through a slug + relative path.

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

### Gevent Safety

**Critical**: All filesystem I/O on `/mnt/vault` (CIFS mount) MUST go through `_run_in_real_thread()` from `orrbit/indexer.py`. Direct calls to `os.stat()`, `Path.exists()`, `os.listdir()`, etc. on CIFS paths will block gevent's event loop and freeze the entire app if the NAS stalls.

The threadpool is configured to 50 real OS threads in `gunicorn.conf.py:post_worker_init()`.

### Frontend

Server-rendered Jinja2 templates with vanilla JS (no framework). Each page has a paired JS file in `static/js/`. Templates extend `templates/base.html`. CSS is in `static/css/style.css` with theme support (built-in themes via `[data-theme]` selectors, third-party via `static/themes/*.css`).

### Key Patterns

- Admin-only endpoints use `@admin_required` decorator from `orrbit/auth.py`
- Settings changes are applied in-memory AND persisted to `config.yaml` via `_write_raw_config()`
- Thumbnails are generated on-demand via ffmpeg/pdftoppm and cached in `data/thumbs/` keyed by md5(path+mtime)
- The upload flow has a staging area (`data/staging/`) where files land before being moved to a permanent directory
- The `Web Share Target API` endpoint (`/upload/share`) is CSRF-exempt since the OS share sheet can't include tokens

## Configuration

`config.yaml` controls everything but is **gitignored** — each deployment has its own. Key fields: `directories` (slug->path map), `users` (seeded on first boot), `indexer`, `thumbnails`, `sftp`, `theme`. See `config.example.yaml` for defaults. Environment overrides: `ORRBIT_APP_NAME`, `ORRBIT_PORT`, `ORRBIT_SECRET_KEY`, `ORRBIT_DATA_DIR`, `ORRBIT_CONFIG`.

### Orrgate Deployment Config

- `tab_title: Orrigins`
- `port: 5001` (5000 is orrapus)
- `directories: { vault: /mnt/vault }`
- `theme: midnight`

## Production

Gunicorn with gevent worker (`gunicorn.conf.py`): single worker, 200 connections, 50-thread pool, no timeout (for long thumbnail generation). Docker image based on python:3.12-slim with ffmpeg and poppler-utils. Runs as uid 3000/gid 4500.
