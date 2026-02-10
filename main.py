"""
Plex Manager - Main entry point
Launches FastAPI web application with Plex OAuth authentication.
"""

import os
import sys
from pathlib import Path
import uvicorn
from dotenv import load_dotenv

from src.console import print_info, print_success, print_warning, print_error

# Load environment variables from .env file
load_dotenv()


def check_configuration() -> bool:
    """
    Check if .env file exists and has all required variables.
    Returns True if configuration is complete, False otherwise.
    """
    env_path = Path('.env')
    
    # Check if .env exists
    if not env_path.exists():
        return False
    
    # Check for all required environment variables
    required_env_vars = [
        "SECRET_KEY",
        "JWT_SECRET_KEY",
        "PLEX_CLIENT_ID",
        "ENCRYPTION_KEY",
        "DATABASE_URL",
        "PLEX_URL",
        "PLEX_TOKEN",
        "TMDB_API_KEY",
        "PROWLARR_URL",
        "PROWLARR_API_KEY",
        "QBITTORRENT_URL",
        "QBITTORRENT_USERNAME",
        "QBITTORRENT_PASSWORD",
        "DOWNLOADS_PATH",
        "MOVIES_PATH",
        "TV_PATH",
        "ENV"
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        print_error(f"Incomplete configuration. Missing {len(missing_vars)} variable(s):", prefix="CONFIG")
        for var in missing_vars:
            print_info(f"  - {var}", prefix="CONFIG")
        return False
    
    return True


def run_setup_wizard():
    """Launch the interactive setup wizard."""
    from src.setup_wizard import run_setup_wizard
    
    print_info("="*70, prefix="SETUP", timestamp=False)
    print_info("Plex Manager is not configured yet.", prefix="SETUP", timestamp=False)
    print_info("="*70, prefix="SETUP", timestamp=False)
    
    success = run_setup_wizard()
    
    if not success:
        print_warning("Setup was not completed. Please run the setup wizard again.", prefix="SETUP")
        sys.exit(1)
    
    # Reload environment variables after setup
    load_dotenv(override=True)


if __name__ == "__main__":
    # Check for --setup flag to force setup wizard
    if "--setup" in sys.argv:
        run_setup_wizard()
        sys.exit(0)
    
    # Check if configuration is complete
    if not check_configuration():
        run_setup_wizard()
    
    # Verify configuration is now complete
    if not check_configuration():
        print_error("Configuration is still incomplete after setup.", prefix="CONFIG")
        sys.exit(1)
    
    print_info("-" * 40, prefix="STARTUP", timestamp=False)
    print_info("Starting Plex Manager...", prefix="STARTUP")
    print_info("-" * 40, prefix="STARTUP", timestamp=False)
    
    # Launch FastAPI application
    uvicorn.run(
        "src.main_api:app",
        host="0.0.0.0",
        port=8000,
        reload=True  # Auto-reload on code changes during development
    )