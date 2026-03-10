#!/usr/bin/env bash
# orrbit — convenience wrapper for common operations

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

case "${1:-help}" in
    setup)
        python3 setup.py
        ;;
    setup-cli)
        shift
        python3 setup_cli.py "$@"
        ;;
    start)
        if [ -f compose.yaml ]; then
            docker compose up -d
            echo "orrbit started. Run 'orrbit.sh logs' to view output."
        else
            echo "No compose.yaml found. Run 'orrbit.sh setup' first."
            exit 1
        fi
        ;;
    stop)
        docker compose down
        echo "orrbit stopped."
        ;;
    restart)
        docker compose restart
        echo "orrbit restarted."
        ;;
    logs)
        docker compose logs -f "${2:-orrbit}"
        ;;
    build)
        docker compose build
        echo "Build complete."
        ;;
    status)
        docker compose ps
        ;;
    deploy)
        if [ -f deploy-vps.sh ]; then
            echo "Re-deploying to VPS..."
            bash deploy-vps.sh
        else
            echo "No deploy-vps.sh found. Run 'orrbit.sh setup' with VPS deployment first."
            exit 1
        fi
        ;;
    sync)
        if [ -f sync.sh ]; then
            bash sync.sh
        else
            echo "No sync.sh found. Run 'orrbit.sh setup' with VPS deployment first."
            exit 1
        fi
        ;;
    tailscale)
        if command -v tailscale &>/dev/null; then
            tailscale status
        else
            echo "Tailscale is not installed. Run 'orrbit.sh setup' to install."
            exit 1
        fi
        ;;
    dev)
        if [ -d .venv ]; then
            .venv/bin/python3 run_dev.py
        else
            python3 -m venv .venv
            .venv/bin/pip install -r requirements.txt
            .venv/bin/python3 run_dev.py
        fi
        ;;
    help|*)
        echo "Usage: orrbit.sh <command>"
        echo ""
        echo "Commands:"
        echo "  setup      Run interactive setup wizard"
        echo "  setup-cli  Run CLI setup (flags or prompted, headless-safe)"
        echo "  start      Start orrbit (Docker)"
        echo "  stop       Stop orrbit (Docker)"
        echo "  restart    Restart orrbit (Docker)"
        echo "  logs       View logs (Docker)"
        echo "  build      Rebuild Docker image"
        echo "  status     Show container status"
        echo "  deploy     Re-deploy to VPS (requires prior setup)"
        echo "  sync       Sync files to VPS (requires prior setup)"
        echo "  tailscale  Show Tailscale status"
        echo "  dev        Start development server"
        echo "  help       Show this help"
        ;;
esac
