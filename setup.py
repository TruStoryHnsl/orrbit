#!/usr/bin/env python3
"""
orrbit setup — Interactive setup wizard.

Generates config.yaml, compose.yaml, and optionally nginx.conf.
Supports advanced deployment: Tailscale, VPS provisioning, domain setup.
"""

import os
import sys
import json
import secrets
import shutil
import socket
import subprocess
import textwrap
import time
from pathlib import Path


# ── Colours ──────────────────────────────────────────────────────────────

def _supports_colour():
    return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

_C = _supports_colour()
BOLD  = '\033[1m'  if _C else ''
DIM   = '\033[2m'  if _C else ''
GREEN = '\033[32m' if _C else ''
CYAN  = '\033[36m' if _C else ''
YELLOW = '\033[33m' if _C else ''
RED   = '\033[31m' if _C else ''
RESET = '\033[0m'  if _C else ''


def banner(text):
    print(f'\n{BOLD}{CYAN}--- {text} ---{RESET}')


def success(text):
    print(f'  {GREEN}✓{RESET} {text}')


def warn(text):
    print(f'  {YELLOW}!{RESET} {text}')


def error(text):
    print(f'  {RED}✗{RESET} {text}')


def info(text):
    print(f'  {DIM}{text}{RESET}')


# ── Prompts ──────────────────────────────────────────────────────────────

def prompt(question, default=None):
    """Prompt user for input with optional default."""
    if default:
        answer = input(f'{question} [{default}]: ').strip()
        return answer if answer else default
    while True:
        answer = input(f'{question}: ').strip()
        if answer:
            return answer


def prompt_yn(question, default=True):
    """Yes/no prompt."""
    hint = 'Y/n' if default else 'y/N'
    answer = input(f'{question} [{hint}]: ').strip().lower()
    if not answer:
        return default
    return answer in ('y', 'yes')


def prompt_choice(question, options):
    """Numbered choice prompt. Returns (number, label) tuple."""
    print(f'\n{question}')
    for i, (label, desc) in enumerate(options, 1):
        print(f'  {BOLD}{i}{RESET}) {label}')
        if desc:
            print(f'     {DIM}{desc}{RESET}')
    while True:
        answer = input(f'  Choice [1-{len(options)}]: ').strip()
        try:
            n = int(answer)
            if 1 <= n <= len(options):
                return n, options[n - 1][0]
        except ValueError:
            pass
        print(f'  Enter a number between 1 and {len(options)}.')


def prompt_directories():
    """Prompt user for directories to serve."""
    banner('Directories')
    print('Enter the directories you want to serve.')
    print('Format: slug path  (e.g. "photos /home/user/Photos")')
    print('Type "done" when finished.\n')

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
            if prompt_yn(f'  "{abs_path}" does not exist. Add anyway?', default=False):
                directories[slug] = abs_path
            continue

        directories[slug] = abs_path
        success(f'{slug} -> {abs_path}')

    return directories


def prompt_user():
    """Prompt for admin user credentials."""
    banner('Admin Account')
    username = prompt('Username', default='admin')
    while True:
        password = prompt('Password')
        if len(password) < 6:
            warn('Password must be at least 6 characters.')
            continue
        break
    return username, password


# ── Utilities ────────────────────────────────────────────────────────────

def get_local_ip():
    """Try to determine the local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return 'localhost'


def run_cmd(cmd, check=True, capture=False, shell=False):
    """Run a shell command, printing it first."""
    if isinstance(cmd, list):
        display = ' '.join(cmd)
    else:
        display = cmd
    info(f'$ {display}')
    kwargs = {'shell': shell}
    if capture:
        kwargs['capture_output'] = True
        kwargs['text'] = True
    result = subprocess.run(cmd, check=check, **kwargs)
    return result


def cmd_exists(name):
    """Check if a command exists on PATH."""
    return shutil.which(name) is not None


def detect_os():
    """Return (distro_family, is_wsl)."""
    import platform
    system = platform.system().lower()
    is_wsl = False
    if system == 'linux':
        try:
            with open('/proc/version', 'r') as f:
                if 'microsoft' in f.read().lower():
                    is_wsl = True
        except FileNotFoundError:
            pass
        # Check distro family
        if Path('/etc/debian_version').exists():
            return 'debian', is_wsl
        if Path('/etc/redhat-release').exists():
            return 'redhat', is_wsl
        if Path('/etc/arch-release').exists():
            return 'arch', is_wsl
        return 'linux', is_wsl
    elif system == 'darwin':
        return 'macos', False
    return system, False


# ── Config Generation ────────────────────────────────────────────────────

def _config_yaml(app_name, port, secret, dir_block, username, password):
    """Build config.yaml from parts."""
    return (
        f'app_name: {app_name}\n'
        f'port: {port}\n'
        f'secret_key: "{secret}"\n'
        f'data_dir: ./data\n'
        f'\n'
        f'directories:\n'
        f'{dir_block}'
        f'\n'
        f'users:\n'
        f'  - username: {username}\n'
        f'    password: {password}\n'
        f'\n'
        f'indexer:\n'
        f'  interval: 1800\n'
        f'  enabled: true\n'
        f'\n'
        f'thumbnails:\n'
        f'  enabled: true\n'
        f'  width: 320\n'
        f'  height: 180\n'
        f'\n'
        f'upload:\n'
        f'  max_size_mb: 500\n'
    )


def generate_config(app_name, port, directories, username, password):
    """Generate config.yaml content with host paths."""
    secret = secrets.token_hex(32)
    dir_block = ''.join(f'  {slug}: {path}\n' for slug, path in directories.items())
    return _config_yaml(app_name, port, secret, dir_block, username, password)


def generate_config_for_docker(app_name, port, directories, username, password):
    """Generate config.yaml with container mount paths."""
    secret = secrets.token_hex(32)
    dir_block = ''.join(f'  {slug}: /mnt/{slug}\n' for slug in directories)
    return _config_yaml(app_name, port, secret, dir_block, username, password)


def generate_compose(directories, port, domain=None, tailscale=False):
    """Generate compose.yaml content."""
    dir_volumes = ''.join(
        f'      - {path}:/mnt/{slug}:ro\n'
        for slug, path in directories.items()
    )

    if domain:
        return (
            'services:\n'
            '  orrbit:\n'
            '    build: .\n'
            '    container_name: orrbit\n'
            '    restart: unless-stopped\n'
            '    expose:\n'
            '      - "5000"\n'
            '    volumes:\n'
            '      - ./config.yaml:/app/config.yaml:ro\n'
            '      - orrbit-data:/app/data\n'
            f'{dir_volumes}'
            '\n'
            '  nginx:\n'
            '    image: nginx:alpine\n'
            '    container_name: orrbit-nginx\n'
            '    restart: unless-stopped\n'
            '    ports:\n'
            '      - "80:80"\n'
            '      - "443:443"\n'
            '    volumes:\n'
            '      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro\n'
            '      - certbot-webroot:/var/www/certbot:ro\n'
            '      - certbot-certs:/etc/letsencrypt:ro\n'
            '    depends_on:\n'
            '      - orrbit\n'
            '\n'
            '  certbot:\n'
            '    image: certbot/certbot\n'
            '    container_name: orrbit-certbot\n'
            '    volumes:\n'
            '      - certbot-webroot:/var/www/certbot\n'
            '      - certbot-certs:/etc/letsencrypt\n'
            "    entrypoint: /bin/sh -c 'trap exit TERM; while :; do certbot renew --webroot -w /var/www/certbot --quiet; sleep 12h & wait $${!}; done'\n"
            '\n'
            'volumes:\n'
            '  orrbit-data:\n'
            '  certbot-webroot:\n'
            '  certbot-certs:\n'
        )

    # No domain — bind directly (optionally on tailscale interface)
    bind_addr = f'0.0.0.0:{port}'
    return (
        'services:\n'
        '  orrbit:\n'
        '    build: .\n'
        '    container_name: orrbit\n'
        '    restart: unless-stopped\n'
        '    ports:\n'
        f'      - "{bind_addr}"\n'
        '    volumes:\n'
        '      - ./config.yaml:/app/config.yaml:ro\n'
        '      - orrbit-data:/app/data\n'
        f'{dir_volumes}'
        '\n'
        'volumes:\n'
        '  orrbit-data:\n'
    )


def generate_nginx(domain):
    """Generate nginx.conf for reverse proxy + SSL."""
    return textwrap.dedent(f"""\
        server {{
            listen 80;
            server_name {domain};

            location /.well-known/acme-challenge/ {{
                root /var/www/certbot;
            }}

            location / {{
                return 301 https://$host$request_uri;
            }}
        }}

        server {{
            listen 443 ssl;
            server_name {domain};

            ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
            ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;

            ssl_protocols TLSv1.2 TLSv1.3;
            ssl_ciphers HIGH:!aNULL:!MD5;
            ssl_prefer_server_ciphers on;

            client_max_body_size 500M;

            location / {{
                proxy_pass http://orrbit:5000;
                proxy_set_header Host $host;
                proxy_set_header X-Real-IP $remote_addr;
                proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                proxy_set_header X-Forwarded-Proto $scheme;

                proxy_http_version 1.1;
                proxy_set_header Upgrade $http_upgrade;
                proxy_set_header Connection "upgrade";
            }}
        }}
    """)


# ── Tailscale ────────────────────────────────────────────────────────────

def detect_tailscale():
    """Check if Tailscale is installed and running."""
    if not cmd_exists('tailscale'):
        return None, None
    try:
        result = subprocess.run(
            ['tailscale', 'status', '--json'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            self_node = data.get('Self', {})
            ts_ips = self_node.get('TailscaleIPs', [])
            ts_ip = ts_ips[0] if ts_ips else None
            hostname = self_node.get('HostName', '')
            dns_name = self_node.get('DNSName', '').rstrip('.')
            return ts_ip, dns_name or hostname
    except Exception:
        pass
    return None, None


def install_tailscale():
    """Guide user through Tailscale installation."""
    banner('Tailscale Installation')
    distro, is_wsl = detect_os()

    if distro == 'macos':
        print('  Tailscale for macOS is installed via the App Store or Homebrew.')
        print()
        print(f'  Option 1: {BOLD}brew install --cask tailscale{RESET}')
        print(f'  Option 2: Download from {CYAN}https://tailscale.com/download/mac{RESET}')
        print()
        input('  Press Enter after installing Tailscale...')

    elif distro in ('debian', 'linux'):
        print('  Installing Tailscale via official install script...')
        print()
        if prompt_yn('  Run: curl -fsSL https://tailscale.com/install.sh | sh ?'):
            run_cmd('curl -fsSL https://tailscale.com/install.sh | sudo sh',
                    shell=True, check=False)
        else:
            print(f'  Manual install: {CYAN}https://tailscale.com/download/linux{RESET}')
            input('  Press Enter after installing Tailscale...')

    elif distro == 'arch':
        print('  Installing Tailscale via pacman...')
        if prompt_yn('  Run: sudo pacman -S tailscale ?'):
            run_cmd(['sudo', 'pacman', '-S', '--noconfirm', 'tailscale'], check=False)
            run_cmd(['sudo', 'systemctl', 'enable', '--now', 'tailscaled'], check=False)
        else:
            input('  Press Enter after installing Tailscale...')

    elif distro == 'redhat':
        print('  Installing Tailscale via official install script...')
        if prompt_yn('  Run: curl -fsSL https://tailscale.com/install.sh | sh ?'):
            run_cmd('curl -fsSL https://tailscale.com/install.sh | sudo sh',
                    shell=True, check=False)
        else:
            input('  Press Enter after installing Tailscale...')

    else:
        print(f'  Visit {CYAN}https://tailscale.com/download{RESET} for your platform.')
        input('  Press Enter after installing Tailscale...')

    # Verify
    if not cmd_exists('tailscale'):
        error('Tailscale not found on PATH after installation.')
        print('  You may need to restart your shell or add it to PATH.')
        return False

    success('Tailscale is installed.')
    return True


def tailscale_authenticate():
    """Run tailscale up to authenticate."""
    banner('Tailscale Authentication')
    ts_ip, _ = detect_tailscale()
    if ts_ip:
        success(f'Already connected. Tailscale IP: {BOLD}{ts_ip}{RESET}')
        return ts_ip

    print('  Starting Tailscale authentication...')
    print('  A browser window will open for you to log in.\n')

    try:
        run_cmd(['sudo', 'tailscale', 'up'], check=False)
    except Exception:
        pass

    # Wait for connection
    print()
    for attempt in range(10):
        ts_ip, _ = detect_tailscale()
        if ts_ip:
            success(f'Connected! Tailscale IP: {BOLD}{ts_ip}{RESET}')
            return ts_ip
        time.sleep(2)

    error('Could not detect Tailscale IP. Check `tailscale status`.')
    ts_ip = prompt('Enter your Tailscale IP manually (from `tailscale ip`)')
    return ts_ip


def setup_tailscale():
    """Full Tailscale setup flow. Returns tailscale IP or None."""
    ts_ip, ts_name = detect_tailscale()

    if ts_ip:
        success(f'Tailscale is running: {BOLD}{ts_ip}{RESET} ({ts_name})')
        return ts_ip

    if cmd_exists('tailscale'):
        warn('Tailscale is installed but not connected.')
        return tailscale_authenticate()

    # Not installed
    print(f'\n  Tailscale is not installed.')
    print(f'  Tailscale creates a private network so you can access orrbit')
    print(f'  from any device without exposing it to the internet.\n')
    print(f'  Free for personal use (up to 100 devices).')
    print(f'  {CYAN}https://tailscale.com{RESET}\n')

    if not prompt_yn('Install Tailscale now?'):
        warn('Skipping Tailscale. You can install it later.')
        return None

    if not install_tailscale():
        return None

    return tailscale_authenticate()


# ── VPS Provisioning ─────────────────────────────────────────────────────

VPS_PROVIDERS = [
    ('Hetzner', 'Best value. CX22 (2 vCPU, 4GB RAM) ~$4.5/mo', 'https://hetzner.cloud'),
    ('DigitalOcean', 'Simple. Basic Droplet (1 vCPU, 1GB) ~$6/mo', 'https://digitalocean.com'),
    ('Vultr', 'Flexible. Cloud Compute (1 vCPU, 1GB) ~$6/mo', 'https://vultr.com'),
    ('Linode/Akamai', 'Reliable. Nanode (1 vCPU, 1GB) ~$5/mo', 'https://linode.com'),
    ('Oracle Cloud', 'Free tier: 4 ARM cores, 24GB RAM', 'https://cloud.oracle.com'),
]


def guide_vps_creation():
    """Walk user through creating a VPS."""
    banner('VPS Server')

    print('  You need a VPS (Virtual Private Server) to host orrbit.')
    print('  If you already have a server, skip ahead.\n')

    n, _ = prompt_choice('Do you already have a server?', [
        ('I have a server', 'Skip to connection details'),
        ('Help me choose a provider', 'Show recommended VPS providers'),
    ])

    if n == 2:
        banner('Recommended VPS Providers')
        for name, desc, url in VPS_PROVIDERS:
            print(f'  {BOLD}{name}{RESET}')
            print(f'    {desc}')
            print(f'    {CYAN}{url}{RESET}')
            print()

        print('  Minimum requirements: 1 vCPU, 512MB RAM, 10GB disk')
        print('  Recommended: 2 vCPU, 2GB RAM for media transcoding')
        print()

        print(f'{BOLD}  Quick-start for Hetzner (best value):{RESET}')
        print('  1. Create account at hetzner.cloud')
        print('  2. New project > Add Server')
        print('  3. Choose: Falkenstein/Nuremberg, Ubuntu 24.04, CX22')
        print('  4. Add your SSH key (or use password)')
        print('  5. Create & Deploy')
        print()

        print(f'{BOLD}  SSH Key setup (if you don\'t have one):{RESET}')
        ssh_key_path = Path.home() / '.ssh' / 'id_ed25519.pub'
        if ssh_key_path.exists():
            success(f'SSH key found: {ssh_key_path}')
            print(f'  Copy this to your VPS provider:')
            try:
                key_content = ssh_key_path.read_text().strip()
                print(f'  {DIM}{key_content[:80]}...{RESET}')
            except Exception:
                pass
        else:
            rsa_key = Path.home() / '.ssh' / 'id_rsa.pub'
            if rsa_key.exists():
                success(f'SSH key found: {rsa_key}')
            else:
                warn('No SSH key found.')
                if prompt_yn('Generate an SSH key now?'):
                    run_cmd(['ssh-keygen', '-t', 'ed25519', '-f',
                             str(Path.home() / '.ssh' / 'id_ed25519'),
                             '-N', ''], check=False)
                    if (Path.home() / '.ssh' / 'id_ed25519.pub').exists():
                        key_content = (Path.home() / '.ssh' / 'id_ed25519.pub').read_text().strip()
                        success('SSH key generated.')
                        print(f'  Public key: {DIM}{key_content[:80]}...{RESET}')
                        print('  Copy this to your VPS provider when creating the server.')

        print()
        input('  Press Enter when your server is ready...')

    # Get server details
    banner('Server Connection')
    vps_ip = prompt('Server IP address')
    vps_user = prompt('SSH user', default='root')
    vps_port = prompt('SSH port', default='22')

    return vps_ip, vps_user, int(vps_port)


def test_ssh(vps_ip, vps_user, vps_port):
    """Test SSH connectivity to VPS."""
    print(f'  Testing SSH connection to {vps_user}@{vps_ip}:{vps_port}...')
    try:
        result = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=accept-new',
             '-p', str(vps_port), f'{vps_user}@{vps_ip}', 'echo "OK"'],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and 'OK' in result.stdout:
            success('SSH connection successful.')
            return True
        else:
            error(f'SSH failed: {result.stderr.strip()}')
            return False
    except subprocess.TimeoutExpired:
        error('SSH connection timed out.')
        return False
    except Exception as e:
        error(f'SSH error: {e}')
        return False


def generate_vps_deploy_script(app_name, port, directories, username, password,
                               domain=None, use_tailscale=False):
    """Generate a self-contained deployment script for the VPS."""
    secret = secrets.token_hex(32)

    # Config with /opt/orrbit paths for synced directories
    dir_block_config = ''.join(f'  {slug}: /opt/orrbit/media/{slug}\n' for slug in directories)
    config_yaml = _config_yaml(app_name, port, secret, dir_block_config, username, password)

    # Compose — map /opt/orrbit/media/<slug> into container
    dir_volumes = ''.join(
        f'      - /opt/orrbit/media/{slug}:/mnt/{slug}:ro\n'
        for slug in directories
    )

    if domain:
        compose_yaml = generate_compose(
            {slug: f'/opt/orrbit/media/{slug}' for slug in directories},
            port, domain=domain,
        )
        nginx_conf = generate_nginx(domain)
    else:
        compose_yaml = (
            'services:\n'
            '  orrbit:\n'
            '    build: /opt/orrbit/app\n'
            '    container_name: orrbit\n'
            '    restart: unless-stopped\n'
            '    ports:\n'
            f'      - "0.0.0.0:{port}:{port}"\n'
            '    volumes:\n'
            '      - /opt/orrbit/config.yaml:/app/config.yaml:ro\n'
            '      - orrbit-data:/app/data\n'
            f'{dir_volumes}'
            '\n'
            'volumes:\n'
            '  orrbit-data:\n'
        )
        nginx_conf = None

    # Build the deploy script
    lines = [
        '#!/usr/bin/env bash',
        'set -e',
        '',
        '# orrbit VPS deployment script',
        f'# Generated by orrbit setup for {app_name}',
        '',
        'echo "=== orrbit VPS deployment ==="',
        '',
        '# 1. Install Docker if not present',
        'if ! command -v docker &>/dev/null; then',
        '    echo "Installing Docker..."',
        '    curl -fsSL https://get.docker.com | sh',
        '    systemctl enable --now docker',
        '    echo "Docker installed."',
        'else',
        '    echo "Docker already installed."',
        'fi',
        '',
        '# Ensure docker compose is available',
        'if ! docker compose version &>/dev/null; then',
        '    echo "Installing Docker Compose plugin..."',
        '    apt-get update && apt-get install -y docker-compose-plugin',
        'fi',
        '',
    ]

    if use_tailscale:
        lines += [
            '# 2. Install Tailscale if not present',
            'if ! command -v tailscale &>/dev/null; then',
            '    echo "Installing Tailscale..."',
            '    curl -fsSL https://tailscale.com/install.sh | sh',
            '    echo "Tailscale installed."',
            'fi',
            '',
            '# Start Tailscale (will prompt for auth)',
            'if ! tailscale status &>/dev/null; then',
            '    echo ""',
            '    echo "=== Tailscale Authentication ==="',
            '    echo "A URL will appear below. Open it in your browser to authenticate."',
            '    echo ""',
            '    tailscale up',
            'fi',
            'TS_IP=$(tailscale ip -4)',
            'echo "Tailscale IP: $TS_IP"',
            '',
        ]

    lines += [
        '# 3. Set up orrbit directory',
        'mkdir -p /opt/orrbit/app',
        'mkdir -p /opt/orrbit/media',
        '',
        '# Create media directories',
    ]
    for slug in directories:
        lines.append(f'mkdir -p /opt/orrbit/media/{slug}')

    lines += [
        '',
        '# 4. Write config',
        'cat > /opt/orrbit/config.yaml << \'ORRBIT_CONFIG\'',
        config_yaml.rstrip(),
        'ORRBIT_CONFIG',
        '',
        '# 5. Write compose.yaml',
        'cat > /opt/orrbit/compose.yaml << \'ORRBIT_COMPOSE\'',
        compose_yaml.rstrip(),
        'ORRBIT_COMPOSE',
        '',
    ]

    if nginx_conf:
        lines += [
            '# 6. Write nginx.conf',
            'cat > /opt/orrbit/nginx.conf << \'ORRBIT_NGINX\'',
            nginx_conf.rstrip(),
            'ORRBIT_NGINX',
            '',
        ]

    lines += [
        '# 7. Clone/copy orrbit source',
        'if [ -d /opt/orrbit/app/orrbit ]; then',
        '    echo "orrbit source already present."',
        'else',
        '    echo "orrbit source will be copied via scp."',
        'fi',
        '',
        '# 8. Build and start',
        'cd /opt/orrbit',
        'docker compose build',
        'docker compose up -d',
        '',
        'echo ""',
        'echo "=== orrbit is running ==="',
    ]

    if domain:
        lines.append(f'echo "Access at: https://{domain}"')
    elif use_tailscale:
        lines.append(f'echo "Access at: http://$TS_IP:{port}"')
    else:
        lines.append(f'echo "Access at: http://$(hostname -I | awk \'{{print $1}}\'):{port}"')

    lines += [
        f'echo "Login: {username} / ********"',
        '',
    ]

    return '\n'.join(lines) + '\n'


def deploy_to_vps(vps_ip, vps_user, vps_port, deploy_script_path, project_dir):
    """Deploy orrbit to a VPS via SSH/SCP."""
    banner('Deploying to VPS')
    ssh_target = f'{vps_user}@{vps_ip}'
    ssh_opts = ['-o', 'StrictHostKeyChecking=accept-new', '-p', str(vps_port)]

    # Step 1: Copy orrbit source to VPS
    print('  Copying orrbit source to server...')
    try:
        run_cmd(['scp', '-r', '-P', str(vps_port),
                 str(project_dir), f'{ssh_target}:/opt/orrbit/app'],
                check=True)
        success('Source code copied.')
    except subprocess.CalledProcessError:
        error('Failed to copy source. Check SSH permissions.')
        print(f'  Manual copy: scp -r -P {vps_port} {project_dir} {ssh_target}:/opt/orrbit/app')
        return False

    # Step 2: Copy deploy script
    print('  Copying deploy script...')
    try:
        run_cmd(['scp', '-P', str(vps_port),
                 str(deploy_script_path), f'{ssh_target}:/opt/orrbit/deploy.sh'],
                check=True)
        success('Deploy script copied.')
    except subprocess.CalledProcessError:
        error('Failed to copy deploy script.')
        return False

    # Step 3: Run deploy script
    print('  Running deployment on server...')
    print(f'  {DIM}This may take a few minutes on first run (Docker pulls).{RESET}')
    print()
    try:
        subprocess.run(
            ['ssh'] + ssh_opts + [ssh_target, 'bash /opt/orrbit/deploy.sh'],
            check=True,
        )
        success('Deployment complete!')
        return True
    except subprocess.CalledProcessError:
        error('Deployment script failed. SSH into server to debug:')
        print(f'  ssh -p {vps_port} {ssh_target}')
        print(f'  cat /opt/orrbit/deploy.sh')
        return False


# ── Domain Setup ─────────────────────────────────────────────────────────

REGISTRARS = [
    ('Cloudflare Registrar', 'At-cost pricing, great DNS', 'https://dash.cloudflare.com'),
    ('Namecheap', 'Affordable, good UI', 'https://namecheap.com'),
    ('Porkbun', 'Cheapest .com, clean UI', 'https://porkbun.com'),
    ('Google Domains (Squarespace)', 'Simple, integrates with Google', 'https://domains.squarespace.com'),
]


def guide_domain_setup(vps_ip=None):
    """Guide user through domain purchase and DNS setup."""
    banner('Domain Setup')

    n, _ = prompt_choice('Do you have a domain name?', [
        ('I already have a domain', 'Skip to DNS configuration'),
        ('Help me get one', 'Show recommended registrars'),
        ('Skip domain setup', 'Use IP address instead'),
    ])

    if n == 3:
        return None

    if n == 2:
        banner('Recommended Domain Registrars')
        for name, desc, url in REGISTRARS:
            print(f'  {BOLD}{name}{RESET} — {desc}')
            print(f'    {CYAN}{url}{RESET}')
        print()
        print('  Tips:')
        print('  - A .com domain typically costs $8-12/year')
        print('  - You only need a domain, not hosting/email')
        print('  - Use a subdomain like files.yourdomain.com')
        print()
        input('  Press Enter when you\'ve registered a domain...')

    domain = prompt('Your domain (e.g. files.example.com)')

    if vps_ip:
        banner('DNS Configuration')
        print(f'  Point your domain to your server:\n')
        print(f'  {BOLD}A Record:{RESET}')
        print(f'    Name: {domain}')
        print(f'    Value: {vps_ip}')
        print(f'    TTL: 300 (or Auto)')
        print()
        print('  If using a subdomain (files.example.com):')
        print(f'    Name: {domain.split(".")[0]}')
        print(f'    Value: {vps_ip}')
        print()

        if prompt_yn('Check DNS propagation now?', default=True):
            check_dns(domain, vps_ip)

    return domain


def check_dns(domain, expected_ip=None):
    """Check if DNS resolves correctly."""
    print(f'  Checking DNS for {domain}...')
    try:
        results = socket.getaddrinfo(domain, 80, socket.AF_INET)
        resolved_ips = list(set(r[4][0] for r in results))
        if resolved_ips:
            success(f'DNS resolves to: {", ".join(resolved_ips)}')
            if expected_ip and expected_ip in resolved_ips:
                success('Matches your server IP!')
                return True
            elif expected_ip:
                warn(f'Expected {expected_ip}, got {", ".join(resolved_ips)}')
                print('  DNS can take up to 48 hours to propagate.')
                print('  Continue anyway — SSL setup will retry.')
                return True
        else:
            warn(f'No A record found for {domain}')
    except socket.gaierror:
        warn(f'DNS lookup failed for {domain}')
        print('  Make sure you\'ve added the A record at your registrar.')
        print('  DNS propagation can take a few minutes to 48 hours.')

    if prompt_yn('Continue anyway?', default=True):
        return True
    return False


def setup_ssl_instructions(domain, vps_ip=None, vps_user=None, vps_port=22):
    """Print SSL setup instructions."""
    banner('SSL Certificate')
    print(f'  After starting orrbit with the domain, get your SSL cert:')
    print()

    if vps_ip and vps_user:
        print(f'  SSH into your server:')
        print(f'    ssh -p {vps_port} {vps_user}@{vps_ip}')
        print()

    email = prompt('Email for SSL certificate (Let\'s Encrypt)', default='admin@example.com')
    print()
    print(f'  Run this command (on the server):')
    print(f'    cd /opt/orrbit')
    print(f'    docker compose run --rm certbot certonly \\')
    print(f'      --webroot -w /var/www/certbot \\')
    print(f'      -d {domain} --agree-tos -m {email}')
    print()
    print(f'  Then restart nginx:')
    print(f'    docker compose restart nginx')
    print()
    return email


# ── VPS + Tailscale Combo ────────────────────────────────────────────────

def setup_vps_tailscale():
    """Guide through VPS with Tailscale (private access, no domain needed)."""
    banner('VPS + Tailscale')
    print('  This setup runs orrbit on a VPS, accessible only via Tailscale.')
    print('  No domain or SSL needed — Tailscale encrypts everything.\n')

    # First ensure local Tailscale
    print(f'{BOLD}  Step 1: Local Tailscale{RESET}')
    print('  You need Tailscale on this machine to access the VPS.\n')
    local_ts_ip = setup_tailscale()
    if not local_ts_ip:
        warn('Local Tailscale setup skipped. You can set it up later.')

    return True


# ── File Sync Guide ──────────────────────────────────────────────────────

def guide_file_sync(directories, vps_ip, vps_user, vps_port):
    """Guide user through syncing files to VPS."""
    banner('File Synchronization')
    print('  Your files need to be on the VPS to be served.')
    print('  Here are your options:\n')

    n, _ = prompt_choice('How do you want to get files onto the server?', [
        ('rsync (recommended)', 'One-time or periodic sync from this machine'),
        ('Upload via orrbit', 'Use the web upload feature (good for small files)'),
        ('Files are already there', 'VPS already has the files'),
        ('I\'ll figure it out later', 'Skip file sync for now'),
    ])

    if n == 1:
        print()
        print(f'{BOLD}  rsync commands to sync your files:{RESET}')
        print()
        for slug, path in directories.items():
            print(f'  # Sync "{slug}":')
            print(f'  rsync -avz --progress -e "ssh -p {vps_port}" \\')
            print(f'    {path}/ {vps_user}@{vps_ip}:/opt/orrbit/media/{slug}/')
            print()

        print('  Tips:')
        print('  - Add --delete to remove files deleted locally')
        print('  - Run periodically with cron for auto-sync')
        print('  - First sync of large libraries will take time')

        # Generate sync script
        sync_lines = ['#!/usr/bin/env bash', '# orrbit file sync script', 'set -e', '']
        for slug, path in directories.items():
            sync_lines.append(f'echo "Syncing {slug}..."')
            sync_lines.append(
                f'rsync -avz --progress -e "ssh -p {vps_port}" '
                f'"{path}/" "{vps_user}@{vps_ip}:/opt/orrbit/media/{slug}/"'
            )
            sync_lines.append('')
        sync_lines.append('echo "Sync complete."')

        sync_script = '\n'.join(sync_lines) + '\n'
        Path('sync.sh').write_text(sync_script)
        os.chmod('sync.sh', 0o755)
        success('Created sync.sh — run it to sync your files.')

    elif n == 3:
        success('Skipping file sync — files already on server.')

    return n


# ── Main Flow ────────────────────────────────────────────────────────────

def main():
    print(f'\n{BOLD}{"=" * 50}')
    print('  orrbit setup')
    print('  Cloud file server')
    print(f'{"=" * 50}{RESET}')

    # App name
    app_name = prompt('\nApp name', default='orrbit')

    # Directories
    directories = prompt_directories()

    # Admin account
    username, password = prompt_user()

    # ── Deployment strategy ──
    banner('Deployment Strategy')
    print('  How do you want to deploy orrbit?\n')

    strategy_n, strategy = prompt_choice('Choose your deployment:', [
        ('Local (Docker)',
         'Run on this machine, access from local network'),
        ('Local + Tailscale',
         'Run on this machine, access from anywhere via Tailscale'),
        ('VPS + Domain (Public)',
         'Deploy to a cloud server with a custom domain and SSL'),
        ('VPS + Tailscale (Private)',
         'Deploy to a cloud server, access via Tailscale only'),
    ])

    output_dir = Path('.')
    port = 5000
    domain = None
    vps_info = None
    ts_ip = None

    # ── Strategy 1: Local Docker ──
    if strategy_n == 1:
        port = int(prompt('Port', default='5000'))

        banner('Generating Files')
        config_content = generate_config_for_docker(
            app_name, 5000, directories, username, password
        )
        compose_content = generate_compose(directories, port)

        (output_dir / 'config.yaml').write_text(config_content)
        success('Created config.yaml')

        (output_dir / 'compose.yaml').write_text(compose_content)
        success('Created compose.yaml')

        local_ip = get_local_ip()
        print(f'\n{BOLD}{"=" * 50}')
        print('  Setup complete!')
        print(f'{"=" * 50}{RESET}')
        print(f'\n  Next steps:')
        print(f'  1. docker compose up -d')
        print(f'  2. Open {CYAN}http://{local_ip}:{port}{RESET}')
        print(f'  Login: {username} / {"*" * len(password)}')

    # ── Strategy 2: Local + Tailscale ──
    elif strategy_n == 2:
        port = int(prompt('Port', default='5000'))
        ts_ip = setup_tailscale()

        banner('Generating Files')
        config_content = generate_config_for_docker(
            app_name, 5000, directories, username, password
        )
        compose_content = generate_compose(directories, port, tailscale=True)

        (output_dir / 'config.yaml').write_text(config_content)
        success('Created config.yaml')

        (output_dir / 'compose.yaml').write_text(compose_content)
        success('Created compose.yaml')

        access_addr = ts_ip or get_local_ip()
        ts_name = None
        if ts_ip:
            _, ts_name = detect_tailscale()

        print(f'\n{BOLD}{"=" * 50}')
        print('  Setup complete!')
        print(f'{"=" * 50}{RESET}')
        print(f'\n  Next steps:')
        print(f'  1. docker compose up -d')
        if ts_ip:
            print(f'  2. Open {CYAN}http://{ts_ip}:{port}{RESET}  (Tailscale)')
            if ts_name:
                print(f'     or  {CYAN}http://{ts_name}:{port}{RESET}  (MagicDNS)')
        else:
            local_ip = get_local_ip()
            print(f'  2. Open {CYAN}http://{local_ip}:{port}{RESET}')
            print(f'     Install Tailscale later to access from anywhere.')
        print(f'\n  Login: {username} / {"*" * len(password)}')

        print(f'\n  {DIM}Tip: Install Tailscale on your phone/laptop to')
        print(f'  access orrbit from anywhere.{RESET}')

    # ── Strategy 3: VPS + Domain ──
    elif strategy_n == 3:
        vps_ip, vps_user, vps_port = guide_vps_creation()

        # Test SSH
        if not test_ssh(vps_ip, vps_user, vps_port):
            if not prompt_yn('SSH failed. Continue anyway?', default=False):
                print('  Fix SSH access and run setup again.')
                return

        # Domain setup
        domain = guide_domain_setup(vps_ip)
        if not domain:
            port = int(prompt('Port (no domain)', default='5000'))

        # Generate deploy script
        banner('Generating Deployment')
        deploy_script = generate_vps_deploy_script(
            app_name, port, directories, username, password,
            domain=domain, use_tailscale=False,
        )

        deploy_path = output_dir / 'deploy-vps.sh'
        deploy_path.write_text(deploy_script)
        os.chmod(str(deploy_path), 0o755)
        success('Created deploy-vps.sh')

        # Also save local configs for reference
        if domain:
            config_content = generate_config_for_docker(
                app_name, 5000, directories, username, password
            )
            (output_dir / 'config.yaml').write_text(config_content)
            compose_content = generate_compose(
                {slug: f'/opt/orrbit/media/{slug}' for slug in directories},
                port, domain=domain,
            )
            (output_dir / 'compose.yaml').write_text(compose_content)
            nginx_content = generate_nginx(domain)
            (output_dir / 'nginx.conf').write_text(nginx_content)
            success('Created config.yaml, compose.yaml, nginx.conf')

        # Deploy?
        if prompt_yn('\nDeploy to server now?', default=True):
            ok = deploy_to_vps(vps_ip, vps_user, vps_port,
                               deploy_path, output_dir)
            if ok:
                # File sync guide
                guide_file_sync(directories, vps_ip, vps_user, vps_port)

                if domain:
                    # SSL instructions
                    setup_ssl_instructions(domain, vps_ip, vps_user, vps_port)

                print(f'\n{BOLD}{"=" * 50}')
                print('  Deployment complete!')
                print(f'{"=" * 50}{RESET}')
                if domain:
                    print(f'\n  Access at: {CYAN}https://{domain}{RESET}')
                    print(f'  (After SSL certificate is set up)')
                else:
                    print(f'\n  Access at: {CYAN}http://{vps_ip}:{port}{RESET}')
                print(f'  Login: {username} / {"*" * len(password)}')
            else:
                print(f'\n  Deploy manually:')
                print(f'  scp -r -P {vps_port} . {vps_user}@{vps_ip}:/opt/orrbit/app')
                print(f'  scp -P {vps_port} deploy-vps.sh {vps_user}@{vps_ip}:/opt/orrbit/')
                print(f'  ssh -p {vps_port} {vps_user}@{vps_ip} "bash /opt/orrbit/deploy.sh"')
        else:
            print(f'\n  To deploy later:')
            print(f'  scp -r -P {vps_port} . {vps_user}@{vps_ip}:/opt/orrbit/app')
            print(f'  scp -P {vps_port} deploy-vps.sh {vps_user}@{vps_ip}:/opt/orrbit/')
            print(f'  ssh -p {vps_port} {vps_user}@{vps_ip} "bash /opt/orrbit/deploy.sh"')

    # ── Strategy 4: VPS + Tailscale ──
    elif strategy_n == 4:
        # Local Tailscale first
        setup_vps_tailscale()

        # VPS details
        vps_ip, vps_user, vps_port = guide_vps_creation()

        if not test_ssh(vps_ip, vps_user, vps_port):
            if not prompt_yn('SSH failed. Continue anyway?', default=False):
                print('  Fix SSH access and run setup again.')
                return

        port = int(prompt('Port', default='5000'))

        # Generate deploy script with Tailscale
        banner('Generating Deployment')
        deploy_script = generate_vps_deploy_script(
            app_name, port, directories, username, password,
            domain=None, use_tailscale=True,
        )

        deploy_path = output_dir / 'deploy-vps.sh'
        deploy_path.write_text(deploy_script)
        os.chmod(str(deploy_path), 0o755)
        success('Created deploy-vps.sh')

        config_content = generate_config_for_docker(
            app_name, 5000, directories, username, password
        )
        (output_dir / 'config.yaml').write_text(config_content)
        compose_content = generate_compose(directories, port, tailscale=True)
        (output_dir / 'compose.yaml').write_text(compose_content)
        success('Created config.yaml, compose.yaml')

        if prompt_yn('\nDeploy to server now?', default=True):
            ok = deploy_to_vps(vps_ip, vps_user, vps_port,
                               deploy_path, output_dir)
            if ok:
                guide_file_sync(directories, vps_ip, vps_user, vps_port)

                print(f'\n{BOLD}{"=" * 50}')
                print('  Deployment complete!')
                print(f'{"=" * 50}{RESET}')
                print(f'\n  The server will get its own Tailscale IP.')
                print(f'  Check it with: ssh -p {vps_port} {vps_user}@{vps_ip} "tailscale ip -4"')
                print(f'\n  Access at: {CYAN}http://<tailscale-ip>:{port}{RESET}')
                print(f'  Login: {username} / {"*" * len(password)}')
                print(f'\n  {DIM}Tip: Install Tailscale on all your devices.')
                print(f'  Everything stays private — no public exposure.{RESET}')
            else:
                print(f'\n  Deploy manually:')
                print(f'  scp -r -P {vps_port} . {vps_user}@{vps_ip}:/opt/orrbit/app')
                print(f'  scp -P {vps_port} deploy-vps.sh {vps_user}@{vps_ip}:/opt/orrbit/')
                print(f'  ssh -p {vps_port} {vps_user}@{vps_ip} "bash /opt/orrbit/deploy.sh"')
        else:
            print(f'\n  To deploy later:')
            print(f'  scp -r -P {vps_port} . {vps_user}@{vps_ip}:/opt/orrbit/app')
            print(f'  scp -P {vps_port} deploy-vps.sh {vps_user}@{vps_ip}:/opt/orrbit/')
            print(f'  ssh -p {vps_port} {vps_user}@{vps_ip} "bash /opt/orrbit/deploy.sh"')

    print()


if __name__ == '__main__':
    main()
