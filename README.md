<div align="center">
  <img src="branding/logo.png" alt="Orrbit logo" width="180" />

# Orrbit

**Self-hosted cloud file server with web UI, PWA, and embedded SFTP.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-3.0+-000000.svg?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker&logoColor=white)](compose.yaml)
[![PWA](https://img.shields.io/badge/PWA-installable-5A0FC8.svg)](#features)

</div>

---

## What it is

Point Orrbit at a few directories on a server and you get a polished web UI for them: thumbnails, full-text search, share links, uploads, multi-user auth, and an embedded SFTP server — all behind a single Docker Compose file. It installs as a PWA on phone and desktop, works offline, and registers itself as an OS share target so you can send files into Orrbit from any app.

It is one Flask process, one SQLite index, one stylesheet, no JS framework, no bundler.

## Why

I wanted Dropbox / Google Drive / iCloud without their hosted control plane. The problem with the consumer cloud isn't the feature set — it's that the files live on someone else's machine, the search index is built by someone else's crawler, and the share link goes through someone else's ACL. I have storage. I have a server. I want a browsable cloud-style UI on top of it.

Existing self-hosted options are either too heavy (Nextcloud's plugin universe, full-app surface, database service) or too thin (basic file listings, no thumbnails, no PWA, no share links). Orrbit is the middle: enough UI to actually use day-to-day from a phone, small enough that one person can read all the source.

Design constraints I held to:

- **Personal-scale first.** Orrbit is what one person runs on one box pointed at the directories they already have. Multi-tenant SaaS scaling is a non-goal. If it works for me on my home server, it ships.
- **Self-hosted means self-hosted.** No external auth, no telemetry, no "free tier with optional cloud." The SQLite index, the thumbnails, the shares — all on the host you control.
- **Function over form, but polish where it matters.** The UI is keyboard-driven (`/` search, `j`/`k` navigate, `f` favorite, `d` download). The PWA installs and registers as a share target. Thumbnails are real, not placeholders. Polish is for the surfaces I touch every day; the rest stays plain.
- **No build step.** Vanilla JS, no React/Vue/Svelte, no bundler, no transpile. Templates are Jinja2, scripts are loose `.js` files paired to templates. Edit a file, refresh the browser.
- **Path safety is one function.** Every filesystem-touching route runs through `path_utils.resolve_path()`. There is no other path-handling code anywhere. If it's not in that function, it can't traverse.

## Architecture

```
                          ┌──────────────────────────────┐
                          │  Browser / PWA / SFTP client │
                          └──────────────┬───────────────┘
                                         │
                              HTTP(S) :5000  /  SFTP :2222
                                         │
                  ┌──────────────────────▼──────────────────────┐
                  │       Gunicorn (1 gevent worker)            │
                  │                                             │
                  │   create_app() → blueprints                 │
                  │   ├─ auth_routes      ├─ share_routes       │
                  │   ├─ browse           ├─ upload_routes      │
                  │   ├─ viewer           ├─ api_routes         │
                  │   └─ settings_routes                        │
                  │                                             │
                  │   path_utils.resolve_path(slug, rel_path)   │
                  │   ── single chokepoint for FS access ──     │
                  └────────┬───────────────────┬────────────────┘
                           │                   │
        ┌──────────────────▼─────┐   ┌─────────▼─────────────────────┐
        │  SQLite (WAL)          │   │  threadpool (gevent hub)      │
        │  data/orrbit_index.db  │   │  - indexer (os.walk)          │
        │   files / shares /     │   │  - thumbs (ffmpeg/pdftoppm)   │
        │   activity_log         │   │  - SFTP (Paramiko)            │
        └────────────────────────┘   └────────────────┬──────────────┘
                                                      │
                                          ┌───────────▼─────────────┐
                                          │  Configured roots       │
                                          │  /srv/documents,        │
                                          │  /srv/media, ...        │
                                          │  (local or NFS/CIFS)    │
                                          └─────────────────────────┘

        ┌──────────────────────────────────────────────────┐
        │  Per-user JSON  data/{favorites,tags,playhead}/  │
        │  ←── easy to back up, migrate, hand-edit ────    │
        └──────────────────────────────────────────────────┘
```

| Component | Path | Role |
|---|---|---|
| App factory | `orrbit/__init__.py` | `create_app()`, blueprint registration, security headers |
| Config | `orrbit/config.py` | YAML loader + `ORRBIT_*` env overrides |
| Auth | `orrbit/auth.py` | Flask-Login, bcrypt, `@admin_required` decorator |
| Path safety | `orrbit/path_utils.py` | `resolve_path(slug, rel_path)` — sole chokepoint |
| Indexer | `orrbit/indexer.py` | Background `os.walk` on threadpool, SQLite WAL writes |
| Thumbnails | `orrbit/thumbnails.py` | On-demand ffmpeg / pdftoppm, cached by `md5(path+mtime)` |
| Shares | `orrbit/shares.py` | Signed share tokens, optional expiry, periodic cleanup |
| Per-user state | `orrbit/{favorites,tags,playhead}.py` + `json_store.py` | Thread-safe JSON-file-per-user |
| Activity | `orrbit/activity.py` | Audit log + retention pruning |
| SFTP | `orrbit/sftp.py` | Optional embedded Paramiko server, same user DB |
| Routes | `orrbit/routes/` | One blueprint per concern |
| Frontend | `templates/` + `static/` | Jinja2 + vanilla JS, no build step |

**Data model.** SQLite (WAL) holds the file index, share tokens, and activity log — three subsystems sharing one DB file. Per-user state (favorites, tags, playheads) lives as JSON-file-per-user so it's trivial to back up, migrate, or hand-edit.

**Gevent safety.** Filesystem I/O against remote mounts (NFS / CIFS / SMB) MUST run on `gevent.get_hub().threadpool`, not directly from a request handler. A stalled remote `os.stat()` from a greenlet freezes the entire worker. The indexer demonstrates the pattern; the rest of the codebase follows it.

## Quickstart

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

Headless install: `python3 setup_cli.py --help`.

### Development

```bash
./orrbit.sh dev               # auto-creates venv, runs run_dev.py

# or manually
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python3 run_dev.py
```

Dev server runs on the port from `config.yaml` (default 5000) with Flask debug + auto-reload.

### Convenience wrapper (`orrbit.sh`)

```text
./orrbit.sh setup       # interactive setup wizard
./orrbit.sh setup-cli   # headless setup
./orrbit.sh dev         # development server
./orrbit.sh start       # docker compose up -d
./orrbit.sh stop        # docker compose down
./orrbit.sh restart     # docker compose restart
./orrbit.sh logs        # docker compose logs -f
./orrbit.sh build       # rebuild image
./orrbit.sh status      # docker compose ps
```

### Configuration

Everything lives in one `config.yaml`. Minimum viable:

```yaml
app_name: orrbit
port: 5000
secret_key: ""          # auto-generated on first boot if empty
data_dir: ./data        # SQLite index, thumb cache, per-user JSON

directories:
  documents: /srv/documents
  media: /srv/media
  photos: /srv/photos

users:
  - username: admin
    password: changeme

indexer:    { enabled: true, interval: 1800 }
thumbnails: { enabled: true, width: 320, height: 180 }
upload:     { max_size_mb: 500 }
sftp:       { enabled: false, port: 2222, read_only: true }
```

See [`config.example.yaml`](config.example.yaml) for the full reference.

Environment overrides (any of these supersede `config.yaml` at runtime):

| Variable | Purpose |
|---|---|
| `ORRBIT_APP_NAME` | Override the branded name shown in the UI |
| `ORRBIT_PORT` | HTTP listen port |
| `ORRBIT_SECRET_KEY` | Flask session secret |
| `ORRBIT_DATA_DIR` | Path to the index, thumb cache, and per-user data |
| `ORRBIT_CONFIG` | Path to the config file |

## Features

**Browse and discover**
- Grid and list views, on-demand thumbnails for video, images, and PDFs (`ffmpeg` + `poppler-utils`)
- Full-text file search backed by a SQLite WAL index that scans roots in the background
- Per-user favorites, tags, and playhead — pick up video / audio playback exactly where you left off
- Activity log of uploads, downloads, shares, and edits, with optional auto-pruning

**View and play**
- In-browser viewers for images, video, audio, PDFs, and text
- Text viewer with raw / reflowed toggle (`?raw=1`)
- Keyboard-driven everywhere: `/` search, `j`/`k` navigate items, `Enter` open, `f` favorite, `d` download, `l`/`g` swap views, arrow keys for prev/next in viewer

**Share and collaborate**
- Signed share links with optional expiry, accessible at `/s/<token>` without an account
- Public upload shares so others can drop files into a folder you control
- Staging area: uploads land in a holding zone before you move them to a permanent root
- Chunked uploads for large files (>50 MB) with resume support

**Mobile and PWA**
- Installable as a Progressive Web App with offline asset caching
- Implements the [Web Share Target API](https://developer.mozilla.org/en-US/docs/Web/Manifest/share_target) — share from any app to Orrbit via the OS share sheet
- Works standalone from the home screen on iOS and Android

**Access everywhere**
- Embedded SFTP server (optional) — slugs become top-level directories, auth uses Orrbit's user DB
- Read-only or read-write modes on port 2222 (default)

**Admin and security**
- Multi-user auth with bcrypt-hashed passwords + admin role
- CSRF on every state-changing route (the OS Share Target endpoint is exempt — share sheets cannot carry tokens)
- Strict security headers: CSP `default-src 'self'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`
- HTTP-only `SameSite=Strict` session cookies
- Path traversal hardening through a single `resolve_path()` chokepoint
- Web-based settings page (admin-only) with live config reload — no SSH required to add a user or a new root

**Theming**
- Built-in dark and light themes via `[data-theme]` CSS selectors
- Drop-in third-party themes via `static/themes/*.css`

## Status

**Single-user / small-group production.** Orrbit runs as the day-to-day personal cloud for the maintainer's home lab and is stable for that use case. Code is small enough that one person can read all of it.

**Audience.** People who already have a home server and want a browsable, share-able UI for the directories they already have. Not for organisations needing SSO, ACLs across thousands of users, or compliance attestations.

**What's NOT yet supported.** No external auth (OAuth/OIDC/LDAP). No object-storage backends — local filesystem (or filesystem-mounted NFS / CIFS) only. No clustering or HA. No automatic TLS — put it behind a reverse proxy. No tests or CI yet (this is a hobby project that prioritises iteration speed over green checkmarks).

## Related projects

Orrbit is part of the broader [TruStoryHnsl](https://github.com/TruStoryHnsl) self-hosted stack:

- [`concord`](https://github.com/TruStoryHnsl/concord) — self-hosted Matrix-based chat platform (same "I want X without their hosted control plane" pattern).
- [`orrbeam`](https://github.com/TruStoryHnsl/orrbeam) — Sunshine/Moonlight remote-desktop mesh; pairs naturally with Orrbit when you want both your files and your desktop on the same self-hosted box.
- [`orracle`](https://github.com/TruStoryHnsl/orracle) — local model training / generation tooling. If Orrbit is "your files, your server", Orracle is "your models, your server."
- [`orrchestrator`](https://github.com/TruStoryHnsl/orrchestrator) — AI dev pipeline hypervisor used to coordinate work across these projects.

## Production notes

- Runs under Gunicorn with a single gevent worker and **no request timeout** — large-PDF / long-video thumbnail generation can take a while.
- Docker base image: `python:3.12-slim` with `ffmpeg`, `poppler-utils`, and `unrar-free`.
- Exposes port **5000** (HTTP) and optionally **2222** (SFTP).
- Place behind a reverse proxy with TLS for any internet-facing deployment. Orrbit does **not** terminate TLS itself.
- Mount data roots into the container as volumes (the setup wizard generates these in `compose.yaml` for you).
- Do not expose the development server (`run_dev.py`) directly to the internet.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Conventional commits, feature branches, no JS bundler.

If you find a security issue, please open an issue tagged `security` rather than disclosing publicly.

## License

MIT — see [LICENSE](LICENSE).
