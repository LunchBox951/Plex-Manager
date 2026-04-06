#!/bin/bash
# Plex Manager - Linux Installer
# Installs Plex Manager and registers it as a systemd service.

set -e

REPO_URL="https://github.com/LunchBox951/Plex-Manager"
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

check_deps() {
    local missing=()
    for cmd in git python3; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        red "ERROR: Missing required commands: ${missing[*]}"
        echo "  Install them with: sudo apt install ${missing[*]}"
        exit 1
    fi

    if ! python3 -m venv --help &>/dev/null; then
        red "ERROR: python3-venv is not installed."
        echo "  Install it with: sudo apt install python3-venv"
        exit 1
    fi
}

# ── Main ──────────────────────────────────────────────────────────────────────

require_root
check_deps

# Determine the user who will own and run the service.
# If invoked via sudo, use the original caller; otherwise use current user.
RUN_USER="${SUDO_USER:-$(whoami)}"
RUN_GROUP="$(id -gn "$RUN_USER")"

blue "Installing Plex Manager"
echo "  Install directory : $INSTALL_DIR"
echo "  Service user      : $RUN_USER ($RUN_GROUP)"
echo ""

# ── Clone / update repository ─────────────────────────────────────────────────

if [ -d "$INSTALL_DIR/.git" ]; then
    blue "Updating existing installation..."
    sudo -u "$RUN_USER" git -C "$INSTALL_DIR" pull --ff-only
else
    blue "Cloning repository..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    chown -R "$RUN_USER:$RUN_GROUP" "$INSTALL_DIR"
fi

# ── Python virtual environment + dependencies ─────────────────────────────────

blue "Setting up Python virtual environment..."
sudo -u "$RUN_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$RUN_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u "$RUN_USER" "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

# ── systemd service ───────────────────────────────────────────────────────────

blue "Installing systemd service..."

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Plex Manager
Documentation=${REPO_URL}
After=network.target qbittorrent.service plexmediaserver.service prowlarr.service
Wants=qbittorrent.service plexmediaserver.service prowlarr.service

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

green ""
green "Installation complete!"
echo ""
echo "  Before starting, configure your environment:"
echo "    sudo -u $RUN_USER cp $INSTALL_DIR/.env.example $INSTALL_DIR/.env"
echo "    sudo -u $RUN_USER \$EDITOR $INSTALL_DIR/.env"
echo ""
echo "  Then start the service:"
echo "    sudo systemctl start $SERVICE_NAME"
echo ""
echo "  Check status / logs:"
echo "    sudo systemctl status $SERVICE_NAME"
echo "    sudo journalctl -u $SERVICE_NAME -f"
