"""
Plex Manager - Main entry point
Launches FastAPI web application with Plex OAuth authentication.
"""

import os
import sys
from pathlib import Path
import uvicorn
from dotenv import load_dotenv

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
        print(f"\nIncomplete configuration. Missing {len(missing_vars)} variable(s):")
        for var in missing_vars:
            print(f"  - {var}")
        return False
    
    return True


def run_setup_wizard():
    """Launch the interactive setup wizard."""
    from src.setup_wizard import run_setup_wizard
    
    print("\n" + "="*70)
    print("Plex Manager is not configured yet.")
    print("="*70)
    
    success = run_setup_wizard()
    
    if not success:
        print("\nSetup was not completed. Please run the setup wizard again.")
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
        print("\nERROR: Configuration is still incomplete after setup.")
        sys.exit(1)
    
    print("-" * 40)
    print("Starting Plex Manager...")
    print("-" * 40)
    
    # Launch FastAPI application
    uvicorn.run(
        "src.main_api:app",
        host="0.0.0.0",
        port=8000,
        reload=True  # Auto-reload on code changes during development
    )