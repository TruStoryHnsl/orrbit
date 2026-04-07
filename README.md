<div align="center">
  <img src="branding/logo.png" alt="Orrbit logo" width="180" />

# Orrbit

**Self-hosted cloud file server with web UI, PWA, and embedded SFTP.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-3.0+-000000.svg?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker&logoColor=white)](compose.yaml)
[![PWA](https://img.shields.io/badge/PWA-installable-5A0FC8.svg)](#mobile-and-pwa)

</div>

---

Orrbit turns any directory on your server into a browsable, searchable cloud file library. Point it at a few folders, give it a config, and you get a polished web UI with thumbnails, search, share links, uploads, multi-user auth, and an embedded SFTP server — all behind a single Docker Compose file.

It installs as a Progressive Web App on phones and desktops, works offline, and registers itself as an OS share target so you can send files into Orrbit from any app on your device.

## Features

### Browse and discover
- **Grid and list views** with on-demand thumbnails for video, images, and PDFs (powered by `ffmpeg` and `poppler-utils`)
- **Full-text file search** backed by a SQLite WAL index that scans your roots in the background
- **Per-user favorites, tags, and playhead** — pick up video and audio playback exactly where you left off
- **Activity log** of uploads, downloads, shares, and edits, with optional auto-pruning

### View and play
- In-browser viewers for images, video, audio, PDFs, and text
- Text viewer with raw / reflowed toggle (`?raw=1`)
- Keyboard-driven everywhere: `/` to search, `j`/`k` to move between items, `Enter` to open, `f` to favorite, `d` to download, `l`/`g` to swap views, arrow keys to step through media

### Share and collaborate
- **Signed share links** with optional expiry, accessible at `/s/<token>` without an account
- **Public upload shares** so others can drop files into a folder you control
- **Staging area** — uploads land in a holding zone before you move them to a permanent root
- **Chunked uploads** for large files (>50 MB) with resume support

### Mobile and PWA
- Installable as a Progressive Web App with offline asset caching
- Implements the [Web Share Target API](https://developer.mozilla.org/en-US/docs/Web/Manifest/share_target) — share from any app to Orrbit via the OS share sheet
- Works standalone from the home screen on iOS and Android

### Access everywhere
- **Embedded SFTP server** (optional) — mount your Orrbit roots in any SFTP client. Slugs become top-level directories and authentication uses Orrbit's user database.
- Read-only or read-write modes
- Runs on port 2222 by default, sharing the same auth as the web UI

### Admin and security
- Multi-user authentication with bcrypt-hashed passwords and an admin role
- CSRF protection on every state-changing route
- Strict security headers: Content-Security-Policy, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`
- HTTP-only `SameSite=Strict` session cookies
- **Path traversal hardening** on every filesystem-touching endpoint via `Path.resolve().relative_to()` checks
- Web-based settings page (admin-only) with live config reload — no SSH required to add a user or a new root

### Theming
- Built-in dark and light themes via `[data-theme]` CSS selectors
- Drop-in third-party themes via `static/themes/*.css`

## Quickstart with Docker

```bash
git clone https://github.com/TruStoryHnsl/orrbit.git
cd orrbit

# Interactive setup wizard — generates config.yaml and compose.yaml
python3 setup.py

# Bring it up
docker compose up -d

# Tail the logs
docker compose logs -f orrbit
```

Open `http://<your-host>:5000` and sign in with the admin credentials you set during setup.

> **Headless install?** Use `python3 setup_cli.py --help` for the non-interactive variant.

## Configuration

Everything is controlled by a single `config.yaml`. The minimum config:

```yaml
app_name: orrbit
port: 5000
secret_key: ""          # auto-generated on first boot if empty

data_dir: ./data        # holds the SQLite index, thumbnail cache, per-user JSON

# Each slug becomes a top-level "root" in the UI
directories:
  documents: /srv/documents
  media: /srv/media
  photos: /srv/photos

# Seeded on first boot; manage users from the Settings page afterwards
users:
  - username: admin
    password: changeme

indexer:
  enabled: true
  interval: 1800        # seconds between full scans

thumbnails:
  enabled: true
  width: 320
  height: 180

upload:
  max_size_mb: 500

# Optional embedded SFTP server
sftp:
  enabled: false
  port: 2222
  read_only: true
```

See [`config.example.yaml`](config.example.yaml) for the full reference.

### Environment overrides

Any of these can be set at runtime to override `config.yaml`:

| Variable | Purpose |
|---|---|
| `ORRBIT_APP_NAME` | Override the branded name shown in the UI |
| `ORRBIT_PORT` | HTTP listen port |
| `ORRBIT_SECRET_KEY` | Flask session secret |
| `ORRBIT_DATA_DIR` | Path to the index, thumb cache, and per-user data |
| `ORRBIT_CONFIG` | Path to the config file |

## Development

```bash
# One-shot dev server with auto-created venv
./orrbit.sh dev

# Or manually
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python3 run_dev.py
```

The dev server runs on the port set in `config.yaml` (default 5000) with Flask debug mode and auto-reload.

### Convenience wrapper

`orrbit.sh` is a thin wrapper over the common operations:

```text
./orrbit.sh setup      # interactive setup wizard
./orrbit.sh setup-cli  # headless setup
./orrbit.sh dev        # development server
./orrbit.sh start      # docker compose up -d
./orrbit.sh stop       # docker compose down
./orrbit.sh restart    # docker compose restart
./orrbit.sh logs       # docker compose logs -f
./orrbit.sh build      # rebuild image
./orrbit.sh status     # docker compose ps
```

## Architecture

Orrbit is a Flask app built with the application-factory pattern and a single Gunicorn gevent worker. The surface area is intentionally small:

```
orrbit/
├── __init__.py        # create_app() factory, blueprints, security headers
├── config.py          # YAML loader + ORRBIT_* env overrides
├── auth.py            # Flask-Login integration, bcrypt, admin roles
├── path_utils.py      # path-traversal-safe slug + relpath resolver
├── indexer.py         # background SQLite indexer (WAL mode)
├── thumbnails.py      # on-demand ffmpeg / pdftoppm thumbs, cached by md5(path+mtime)
├── shares.py          # signed share links with optional expiry
├── favorites.py       # per-user JSON store
├── tags.py            # per-user JSON store
├── playhead.py        # per-user JSON store (resume playback)
├── activity.py        # activity log + optional pruning
├── sftp.py            # embedded Paramiko SFTP server (optional)
├── json_store.py      # thread-safe JSON-file-per-user abstraction
└── routes/
    ├── auth_routes.py
    ├── browse.py
    ├── viewer.py
    ├── share_routes.py
    ├── upload_routes.py
    ├── api_routes.py
    └── settings_routes.py
```

### Data model

Orrbit uses a deliberate **dual storage** model:

- **SQLite** (`data/orrbit_index.db`, WAL mode) holds the file index, share tokens, and the activity log — three subsystems sharing one database file.
- **Per-user JSON** (`data/{favorites,tags,playhead}/<username>.json`) is managed by `JsonStore`, a small thread-safe JSON-file-per-user abstraction. This keeps user state easy to back up, migrate, or hand-edit.

### Path security

Every route that touches the filesystem goes through `orrbit/path_utils.py:resolve_path(slug, rel_path)`. It validates that the slug exists in the configured directory map and uses `Path.resolve().relative_to()` to reject any request that escapes its root. There is no other path-handling code anywhere in the app.

### Background services

- **Indexer** — periodic `os.walk` scans run on `gevent.get_hub().threadpool` so slow NFS / CIFS I/O never blocks the event loop.
- **Share cleanup** — purges expired tokens every 5 minutes.
- **Activity pruning** — optional, drops entries older than `activity.retention_days` every 6 hours.
- **SFTP server** — optional embedded Paramiko server authenticating against the same user database as the web UI.

### Frontend

Server-rendered Jinja2 templates plus vanilla JavaScript — **no build step, no framework, no bundler**. Each template has a paired JS file in `static/js/`. CSS is a single stylesheet (`static/css/style.css`) using CSS variables for theming.

## Project layout

```text
.
├── orrbit/             # Python package (Flask app)
├── static/             # CSS, JS, PWA manifest, icons, themes
├── templates/          # Jinja2 templates
├── Dockerfile
├── compose.yaml
├── config.example.yaml
├── gunicorn.conf.py
├── requirements.txt
├── run_dev.py          # dev server entrypoint
├── run_prod.py         # gunicorn entrypoint
├── setup.py            # interactive setup wizard
├── setup_cli.py        # headless setup
└── orrbit.sh           # convenience wrapper
```

## Production notes

- Runs under Gunicorn with a single gevent worker and **no request timeout** — thumbnail generation for large PDFs and long videos can take a while.
- Docker image is `python:3.12-slim` with `ffmpeg`, `poppler-utils`, and `unrar-free`.
- Exposes port **5000** (HTTP) and optionally **2222** (SFTP).
- Place behind a reverse proxy with TLS for any internet-facing deployment. Orrbit does **not** terminate TLS itself.
- Mount your data roots into the container as volumes (the setup wizard generates these for you in `compose.yaml`).

## Security

Orrbit ships with sensible defaults:

- bcrypt password hashing
- HTTP-only, `SameSite=Strict` session cookies
- A strict Content Security Policy (`default-src 'self'`)
- CSRF protection on all state-changing routes (the OS Share Target endpoint is exempted because the share sheet cannot carry a token)
- Path traversal prevention on every filesystem endpoint
- `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`

**Do not expose the development server directly to the internet.** Run the Docker image behind a reverse proxy with TLS.

If you find a security issue, please open an issue marked `security` rather than disclosing publicly.

## Contributing

Contributions are welcome. This is a hobby project first — the goal is keeping Orrbit small, reliable, and easy for one person to operate. Please:

1. Open an issue before larger changes so we can discuss scope
2. Match the existing code style (vanilla Python, no frameworks beyond Flask, no JS bundler)
3. Keep commits focused — one logical change per commit
4. Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages (`feat:`, `fix:`, `docs:`, `refactor:`, etc.)

## License

MIT — see [LICENSE](LICENSE).
