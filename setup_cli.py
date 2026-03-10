#!/usr/bin/env python3
"""
orrbit setup-cli — Config generation for headless or interactive use.

Pass flags for fully non-interactive use, or omit them to be prompted.
The output is identical regardless of where you run it.

Usage:
    python3 setup_cli.py                                            # prompted for everything
    python3 setup_cli.py --dir media=/mnt/media --user admin:secret # no prompts needed
    python3 setup_cli.py --dir media=/mnt/media --domain files.example.com --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

from setup import (
    generate_config_for_docker,
    generate_compose,
    generate_nginx,
    get_local_ip,
    BOLD, CYAN, RESET, DIM, success, warn,
    error as print_error,
)


# ── Argument helpers ────────────────────────────────────────────────────

def parse_dir(value):
    """Parse 'slug=path' directory argument."""
    if '=' not in value:
        raise argparse.ArgumentTypeError(
            f"Invalid directory format '{value}'. Use slug=/path/to/dir")
    slug, path = value.split('=', 1)
    slug = slug.strip()
    path = os.path.expanduser(path.strip())
    abs_path = str(Path(path).resolve())
    if not slug:
        raise argparse.ArgumentTypeError('Directory slug cannot be empty')
    return slug, abs_path


def parse_user(value):
    """Parse 'username:password' credential argument."""
    if ':' not in value:
        raise argparse.ArgumentTypeError(
            f"Invalid user format '{value}'. Use username:password")
    username, password = value.split(':', 1)
    return username.strip(), password


def write_or_print(path, content, dry_run):
    """Write a file to disk, or print it in dry-run mode."""
    if dry_run:
        print(f'\n{BOLD}── {path} ──{RESET}')
        print(content)
        return
    Path(path).write_text(content)
    success(f'Created {path}')


# ── Interactive fallbacks ───────────────────────────────────────────────

def prompt_directories():
    """Prompt for directories when --dir is not provided."""
    print(f'\n{BOLD}Directories to serve{RESET}')
    print(f'  {DIM}Format: slug /path/to/dir  (e.g. "photos /home/user/Photos"){RESET}')
    print(f'  {DIM}Type "done" when finished.{RESET}\n')

    directories = {}
    while True:
        entry = input('  Directory (or "done"): ').strip()
        if entry.lower() == 'done':
            if not directories:
                warn('You must add at least one directory.')
                continue
            break
        if not entry:
            continue

        parts = entry.split(None, 1)
        if len(parts) < 2:
            warn('Format: slug /path/to/directory')
            continue

        slug, path = parts
        path = os.path.expanduser(path)
        abs_path = str(Path(path).resolve())

        if not Path(abs_path).is_dir():
            answer = input(f'  "{abs_path}" does not exist. Add anyway? [y/N]: ').strip().lower()
            if answer in ('y', 'yes'):
                directories[slug] = abs_path
            continue

        directories[slug] = abs_path
        success(f'{slug} -> {abs_path}')

    return directories


def prompt_user():
    """Prompt for admin credentials when --user is not provided."""
    print(f'\n{BOLD}Admin Account{RESET}')
    username = input(f'  Username [admin]: ').strip() or 'admin'
    while True:
        password = input(f'  Password: ').strip()
        if not password:
            warn('Password cannot be empty.')
            continue
        if len(password) < 6:
            warn('Password must be at least 6 characters.')
            continue
        break
    return username, password


def prompt_domain():
    """Prompt for optional domain when --domain is not provided."""
    print(f'\n{BOLD}Domain (optional){RESET}')
    print(f'  {DIM}If you have a domain, entering it adds nginx + SSL config.{RESET}')
    print(f'  {DIM}Leave blank to skip.{RESET}')
    domain = input(f'  Domain (e.g. files.example.com): ').strip()
    return domain or None


# ── Core logic ──────────────────────────────────────────────────────────

def run(args):
    """Generate config files, prompting for missing values."""
    # Directories — prompt if none provided
    if args.dir:
        directories = dict(args.dir)
        for slug, path in directories.items():
            if not Path(path).is_dir():
                warn(f'Directory does not exist: {path} (slug: {slug})')
    else:
        directories = prompt_directories()

    # User — prompt if not provided
    if args.user is not None:
        username, password = args.user
        if len(password) < 6:
            print_error('Password must be at least 6 characters.')
            sys.exit(1)
    else:
        username, password = prompt_user()

    # Domain — prompt if not explicitly provided or skipped
    if args.domain is not None:
        domain = args.domain or None
    elif not args.no_prompt:
        domain = prompt_domain()
    else:
        domain = None

    out = Path(args.output_dir)

    # Generate config.yaml
    config = generate_config_for_docker(args.name, 5000, directories, username, password)
    write_or_print(out / 'config.yaml', config, args.dry_run)

    # Generate compose.yaml (with or without nginx)
    if domain:
        compose = generate_compose(directories, args.port, domain=domain)
        nginx = generate_nginx(domain)
        write_or_print(out / 'compose.yaml', compose, args.dry_run)
        write_or_print(out / 'nginx.conf', nginx, args.dry_run)
    else:
        compose = generate_compose(directories, args.port)
        write_or_print(out / 'compose.yaml', compose, args.dry_run)

    # Summary
    if not args.dry_run:
        local_ip = get_local_ip()
        print(f'\n{BOLD}Setup complete!{RESET}')
        print(f'  1. docker compose up -d')
        if domain:
            print(f'  2. Open {CYAN}https://{domain}{RESET}')
        else:
            print(f'  2. Open {CYAN}http://{local_ip}:{args.port}{RESET}')
        print(f'  Login: {username} / {"*" * len(password)}')


# ── Argument parser ─────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog='setup_cli.py',
        description='orrbit setup — Config generation. Omit flags to be prompted.',
    )
    parser.add_argument('--name', default='orrbit',
                        help='App name (default: orrbit)')
    parser.add_argument('--port', type=int, default=5000,
                        help='Port (default: 5000)')
    parser.add_argument('--dir', type=parse_dir, action='append', default=[],
                        metavar='SLUG=PATH',
                        help='Directory to serve (repeatable, prompted if omitted)')
    parser.add_argument('--user', type=parse_user, default=None,
                        metavar='USER:PASS',
                        help='Admin credentials (prompted if omitted)')
    parser.add_argument('--domain', default=None,
                        help='Domain name — adds nginx.conf with SSL (prompted if omitted)')
    parser.add_argument('--output-dir', default='.',
                        help='Output directory for generated files (default: .)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print generated files to stdout without writing')
    parser.add_argument('--no-prompt', action='store_true',
                        help='Never prompt — error on missing required values')
    return parser


# ── Main ────────────────────────────────────────────────────────────────

def main():
    parser = build_parser()
    args = parser.parse_args()

    # In no-prompt mode, validate that required values are present
    if args.no_prompt:
        if not args.dir:
            print_error('--dir is required in --no-prompt mode.')
            sys.exit(1)
        if args.user is None:
            print_error('--user is required in --no-prompt mode.')
            sys.exit(1)

    run(args)


if __name__ == '__main__':
    main()
