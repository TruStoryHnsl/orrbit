# Contributing to Orrbit

Orrbit is a hobby project first. The goal is keeping it small, reliable, and
easy for one person to operate. Contributions are welcome — within that frame.

## Before you start

- For non-trivial changes, **open an issue first** so we can discuss scope. A
  rejected PR after a weekend of work is worse for everyone than a five-minute
  conversation up front.
- Skim the [README's Architecture section](README.md#architecture). The codebase
  has a few load-bearing rules (single `path_utils.resolve_path()` chokepoint,
  gevent-threadpool for remote-FS I/O, no JS bundler) that will save you time
  if you know them up front.

## Filing an issue

Use the appropriate template:

- **Bug report** — reproducible misbehaviour. Include the version / commit, the
  deployment mode (Docker vs bare metal), and the storage backend (local disk
  vs NFS/CIFS). Logs from `docker compose logs --tail=200 orrbit` help.
- **Feature request** — describe the *problem*, not just the solution. Mark the
  scope honestly: "just me", "would-like-to-share", or "commercial-fit". Most
  features that land are small, opt-in, and don't grow the dependency list.
- **Security** — please use [GitHub's private vulnerability reporting](https://github.com/TruStoryHnsl/orrbit/security/advisories/new)
  rather than opening a public issue.

## Opening a PR

1. **Branch from `main`.** Use one of:
   - `feat/<slug>` — new feature
   - `fix/<slug>` — bug fix (or `fix/<issue-number>-<slug>` if there's a tracking issue)
   - `refactor/<slug>` — refactor without behaviour change
   - `chore/<slug>` — tooling, deps, docs-only changes that don't fit `docs:`
   - `docs/<slug>` — documentation
2. **Branch isolation matters.** Don't commit directly to `main`, don't merge
   `main` into your branch mid-flight unless asked, and don't piggyback on
   somebody else's open branch. Each PR should be one self-contained slice of
   work.
3. **Conventional Commits.** Every commit message follows the
   [Conventional Commits](https://www.conventionalcommits.org/) spec:
   ```
   <type>[optional scope]: <description>

   [optional body]

   [optional footer(s)]
   ```
   Types: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `chore`, `ci`, `build`.
   Breaking changes: `feat!:` / `fix!:` / a `BREAKING CHANGE:` footer.
4. **Keep commits focused.** One logical change per commit. Squash fixup commits
   before requesting review.
5. **Match the existing code style.** Vanilla Python (no opinionated formatter
   wars), no frameworks beyond Flask, no JS bundler. Templates live in
   `templates/`, paired JS in `static/js/<page>.js`. CSS variables for theming.
6. **Path safety is non-negotiable.** Any new route that touches the filesystem
   must go through `orrbit.path_utils.resolve_path(slug, rel_path)`. Adding a
   second path-handling code path will block the PR.
7. **Gevent safety.** Anything that hits a remote mount (NFS / CIFS / SMB) must
   run on `gevent.get_hub().threadpool`, not directly from a request handler.
   See `orrbit/indexer.py` for the pattern.
8. **Open the PR using [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md).**
   Fill in the test plan honestly — "I clicked through it" is fine, but say
   what you clicked.

## What's likely to get merged

- Bug fixes with a reproduction.
- Self-contained features that don't grow the dependency list, don't break the
  no-bundler rule, and don't require a database service.
- Documentation improvements.
- Theme contributions (drop a `.css` file in `static/themes/`).

## What's likely to get pushback

- Adding a JS framework / build step.
- Pulling in a database service (Postgres, Redis, etc.) — SQLite is sufficient.
- External-auth integrations (OAuth, OIDC, LDAP) — possible but a big surface
  to maintain. Discuss before building.
- Anything that requires breaking the single-process / single-binary deployment
  model.
- Telemetry, analytics, "phone home" features. Hard no.

## License

By contributing, you agree your contribution is licensed under the project's
[MIT License](LICENSE).
