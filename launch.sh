#!/bin/bash

# Exit immediately on error
set -e

# Change to repo root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Ensure .env exists
if [ ! -f .env ]; then
    echo "ERROR: .env file not found!"
    echo "Copy .env.example, fill out variables, then try again."
    exit 1
fi

# Check if Python 3 is installed
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 not found."
    exit 2
fi

PYTHON=python3

# Ensure python3-venv is installed
if ! "$PYTHON" -m venv --help &>/dev/null; then
    echo "ERROR: python3-venv package is missing. Try:"
    echo "    sudo apt install python3-venv"
    exit 3
fi

# Create virtual environment if missing
if [ ! -d "venv" ]; then
    echo "Creating virtual environment in ./venv..."
    "$PYTHON" -m venv venv
fi

# Always use the venv python/pip
source venv/bin/activate

# Upgrade pip in venv, allow break-system-packages if needed
python -m pip install --upgrade pip --break-system-packages || python -m pip install --upgrade pip

# Install dependencies
if [ -f requirements.txt ]; then
    echo "Installing dependencies from requirements.txt..."
    pip install --break-system-packages -r requirements.txt || pip install -r requirements.txt
else
    echo "ERROR: requirements.txt not found!"
    deactivate
    exit 4
fi

# Start Plex Manager
echo "Starting Plex Manager..."
python main.py

# Deactivate venv after
deactivate