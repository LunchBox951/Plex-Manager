#!/bin/bash
# Plex Manager - Linux Updater
# Pulls the latest code and refreshes dependencies. Restarts the service if running.

set -e

INSTALL_DIR="/opt/plex-manager"
SERVICE_NAME="plex-manager"

# ── Helpers ───────────────────────────────────────────────────────────────────

red()   { echo -e "\033[0;31m$*\033[0m"; }
green() { echo -e "\033[0;32m$*\033[0m"; }
blue()  { echo -e "\033[0;34m$*\033[0m"; }

require_root() {
    if [ "$EUID" -ne 0 ]; then
        red "ERROR: This script must be run as root (use sudo)."
        exit 1
    fi
}

# ── Main ──────────────────────────────────────────────────────────────────────

require_root

if [ ! -d "$INSTALL_DIR/.git" ]; then
    red "ERROR: No Plex Manager installation found at $INSTALL_DIR."
    echo "  Run the installer first: sudo bash .install/linux.sh"
    exit 1
fi

RUN_USER="$(stat -c '%U' "$INSTALL_DIR")"

blue "Updating Plex Manager"
echo "  Install directory : $INSTALL_DIR"
echo "  Service user      : $RUN_USER"
echo ""

# ── Stop service if running ───────────────────────────────────────────────────

WAS_RUNNING=false
if systemctl is-active --quiet "$SERVICE_NAME"; then
    blue "Stopping service..."
    systemctl stop "$SERVICE_NAME"
    WAS_RUNNING=true
fi

# ── Pull latest code ──────────────────────────────────────────────────────────

blue "Pulling latest code..."
sudo -u "$RUN_USER" git -C "$INSTALL_DIR" pull --ff-only

# ── Refresh dependencies ──────────────────────────────────────────────────────

blue "Refreshing dependencies..."
sudo -u "$RUN_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u "$RUN_USER" "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

# ── Restart service if it was running ────────────────────────────────────────

if [ "$WAS_RUNNING" = true ]; then
    blue "Restarting service..."
    systemctl start "$SERVICE_NAME"
fi

green ""
green "Update complete!"
echo ""
echo "  Check status / logs:"
echo "    sudo systemctl status $SERVICE_NAME"
echo "    sudo journalctl -u $SERVICE_NAME -f"
