#!/bin/bash
# Plex Manager - Linux Uninstaller
# Stops and removes the systemd service and install directory.

set -e

INSTALL_DIR="/opt/plex-manager"
SERVICE_NAME="plex-manager"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

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

blue "Uninstalling Plex Manager"
echo ""

# ── Stop and disable service ──────────────────────────────────────────────────

if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    blue "Stopping service..."
    systemctl stop "$SERVICE_NAME"
fi

if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    blue "Disabling service..."
    systemctl disable "$SERVICE_NAME"
fi

if [ -f "$SERVICE_FILE" ]; then
    blue "Removing service file..."
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
fi

# ── Remove install directory ──────────────────────────────────────────────────

if [ -d "$INSTALL_DIR" ]; then
    blue "Removing $INSTALL_DIR..."
    rm -rf "$INSTALL_DIR"
else
    echo "  $INSTALL_DIR not found, skipping."
fi

green ""
green "Uninstall complete."
