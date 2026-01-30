"""
Plex Manager - Main entry point
Launches FastAPI web application with Plex OAuth authentication.
"""

import os
import uvicorn
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Verify required environment variables
required_env_vars = ["SECRET_KEY", "PLEX_CLIENT_ID", "ENCRYPTION_KEY"]
missing_vars = [var for var in required_env_vars if not os.getenv(var)]

if missing_vars:
    print("ERROR: Missing required environment variables:")
    for var in missing_vars:
        print(f"  - {var}")
    print("\nPlease create a .env file based on .env.example")
    print("Run these commands to generate keys:")
    print("  python -c \"import secrets; print(f'SECRET_KEY={secrets.token_urlsafe(32)}')\"")
    print("  python -c \"import uuid; print(f'PLEX_CLIENT_ID={uuid.uuid4()}')\"")
    print("  python -c \"from cryptography.fernet import Fernet; print(f'ENCRYPTION_KEY={Fernet.generate_key().decode()}')\"")
    exit(1)

if __name__ == "__main__":
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