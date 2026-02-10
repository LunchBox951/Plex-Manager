"""
Interactive setup wizard for first-run configuration of Plex Manager.
Automatically generates secrets, validates services, and creates .env file.
"""

import os
import sys
import secrets
import uuid
from pathlib import Path
from typing import Dict, Optional, Tuple
from cryptography.fernet import Fernet
import requests
from plexapi.server import PlexServer
from qbittorrentapi import Client as QBittorrentClient

from src.console import print_info, print_success, print_warning, print_error, Colors


def print_header(text: str):
    """Print a colored header."""
    print(f"\n{Colors.BOLD}{Colors.HEADER}{'='*70}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.HEADER}{text}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.HEADER}{'='*70}{Colors.ENDC}\n")


def parse_env_file(env_path: Path) -> Dict[str, str]:
    """Parse existing .env file and return key-value pairs."""
    env_vars = {}
    if not env_path.exists():
        return env_vars
    
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            # Parse key=value pairs
            if '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    
    return env_vars


def generate_secret_key() -> str:
    """Generate a random secret key for JWT tokens."""
    return secrets.token_urlsafe(32)


def generate_encryption_key() -> str:
    """Generate a Fernet encryption key."""
    return Fernet.generate_key().decode()


def generate_client_id() -> str:
    """Generate a UUID for Plex client ID."""
    return str(uuid.uuid4())


def ensure_application_directories():
    """Create application directories if they don't exist."""
    dirs = [
        'data',
        'cache',
        'cache/images',
        'cache/images/w185',
        'cache/images/w500',
    ]
    
    for dir_path in dirs:
        path = Path(dir_path)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            # Create .gitkeep file
            gitkeep = path / '.gitkeep'
            gitkeep.touch()
            print_success(f"Created directory: {dir_path}", timestamp=False)


def validate_plex_connection(url: str, token: str) -> Tuple[bool, str]:
    """
    Validate Plex server connection and token.
    Returns (success, message).
    """
    try:
        plex = PlexServer(url, token, timeout=10)
        server_name = plex.friendlyName
        return True, f"Connected to Plex server: {server_name}"
    except Exception as e:
        return False, f"Failed to connect to Plex: {str(e)}"


def validate_tmdb_api_key(api_key: str) -> Tuple[bool, str]:
    """
    Validate TMDB API key by making a test request.
    Returns (success, message).
    """
    try:
        url = f"https://api.themoviedb.org/3/configuration?api_key={api_key}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            return True, "TMDB API key is valid"
        elif response.status_code == 401:
            return False, "Invalid TMDB API key"
        else:
            return False, f"TMDB API error: {response.status_code}"
    except Exception as e:
        return False, f"Failed to validate TMDB API key: {str(e)}"


def validate_prowlarr_connection(url: str, api_key: str) -> Tuple[bool, str]:
    """
    Validate Prowlarr connection and API key.
    Returns (success, message).
    """
    try:
        headers = {'X-Api-Key': api_key}
        test_url = f"{url.rstrip('/')}/api/v1/health"
        response = requests.get(test_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return True, "Connected to Prowlarr successfully"
        elif response.status_code == 401:
            return False, "Invalid Prowlarr API key"
        else:
            return False, f"Prowlarr connection error: {response.status_code}"
    except requests.exceptions.ConnectionError:
        return False, f"Cannot connect to Prowlarr at {url}. Is Prowlarr running?"
    except Exception as e:
        return False, f"Failed to connect to Prowlarr: {str(e)}"


def validate_qbittorrent_connection(url: str, username: str, password: str) -> Tuple[bool, str]:
    """
    Validate qBittorrent connection and credentials.
    Returns (success, message).
    """
    try:
        client = QBittorrentClient(
            host=url,
            username=username,
            password=password,
            VERIFY_WEBUI_CERTIFICATE=False
        )
        client.auth_log_in()
        version = client.app.version
        client.auth_log_out()
        return True, f"Connected to qBittorrent v{version}"
    except Exception as e:
        error_msg = str(e)
        if "Forbidden" in error_msg or "401" in error_msg or "403" in error_msg:
            return False, "Invalid qBittorrent username or password"
        elif "Connection" in error_msg:
            return False, f"Cannot connect to qBittorrent at {url}. Is qBittorrent running?"
        else:
            return False, f"Failed to connect to qBittorrent: {error_msg}"


def validate_path(path: str, path_name: str) -> Tuple[bool, str]:
    """
    Validate that a path exists and is writable.
    Returns (success, message).
    """
    path_obj = Path(path)
    
    if not path_obj.exists():
        return False, f"{path_name} does not exist: {path}"
    
    if not path_obj.is_dir():
        return False, f"{path_name} is not a directory: {path}"
    
    # Test write permissions
    try:
        test_file = path_obj / '.plex_manager_test'
        test_file.touch()
        test_file.unlink()
        return True, f"{path_name} is valid and writable"
    except Exception as e:
        return False, f"{path_name} is not writable: {str(e)}"


def prompt_with_default(prompt: str, default: str = "") -> str:
    """Prompt user for input with optional default value."""
    if default:
        user_input = input(f"{prompt} [{default}]: ").strip()
        return user_input if user_input else default
    else:
        return input(f"{prompt}: ").strip()


def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    """Prompt user for yes/no confirmation."""
    default_str = "Y/n" if default else "y/N"
    response = input(f"{prompt} [{default_str}]: ").strip().lower()
    
    if not response:
        return default
    return response in ['y', 'yes']


def prompt_with_validation(
    prompt: str,
    validator_func,
    default: str = "",
    help_text: str = "",
    max_attempts: int = 3
) -> Optional[str]:
    """
    Prompt user for input with validation.
    Returns None if validation fails after max_attempts.
    """
    if help_text:
        print_info(help_text)
    
    attempts = 0
    while attempts < max_attempts:
        value = prompt_with_default(prompt, default)
        
        if not value:
            print_error("Value cannot be empty")
            attempts += 1
            continue
        
        # Validate the input
        success, message = validator_func(value)
        
        if success:
            print_success(message)
            return value
        else:
            print_error(message)
            attempts += 1
            
            if attempts < max_attempts:
                retry = prompt_yes_no(f"Retry? ({max_attempts - attempts} attempts remaining)", default=True)
                if not retry:
                    return None
    
    print_error(f"Max attempts ({max_attempts}) reached. Please check your configuration and try again.")
    return None


def setup_secrets(existing_config: Dict[str, str]) -> Dict[str, str]:
    """Setup or validate secret keys."""
    print_header("Step 1: Security Keys")
    print_info("Generating cryptographic keys for secure operation...", timestamp=False)
    
    config = {}
    
    # SECRET_KEY
    if 'SECRET_KEY' in existing_config and existing_config['SECRET_KEY']:
        print_success(f"Using existing SECRET_KEY", timestamp=False)
        config['SECRET_KEY'] = existing_config['SECRET_KEY']
    else:
        config['SECRET_KEY'] = generate_secret_key()
        print_success("Generated new SECRET_KEY", timestamp=False)
    
    # JWT_SECRET_KEY
    if 'JWT_SECRET_KEY' in existing_config and existing_config['JWT_SECRET_KEY']:
        print_success(f"Using existing JWT_SECRET_KEY", timestamp=False)
        config['JWT_SECRET_KEY'] = existing_config['JWT_SECRET_KEY']
    else:
        config['JWT_SECRET_KEY'] = generate_secret_key()
        print_success("Generated new JWT_SECRET_KEY", timestamp=False)
    
    # PLEX_CLIENT_ID
    if 'PLEX_CLIENT_ID' in existing_config and existing_config['PLEX_CLIENT_ID']:
        print_success(f"Using existing PLEX_CLIENT_ID", timestamp=False)
        config['PLEX_CLIENT_ID'] = existing_config['PLEX_CLIENT_ID']
    else:
        config['PLEX_CLIENT_ID'] = generate_client_id()
        print_success("Generated new PLEX_CLIENT_ID", timestamp=False)
    
    # ENCRYPTION_KEY
    if 'ENCRYPTION_KEY' in existing_config and existing_config['ENCRYPTION_KEY']:
        print_success(f"Using existing ENCRYPTION_KEY", timestamp=False)
        config['ENCRYPTION_KEY'] = existing_config['ENCRYPTION_KEY']
    else:
        config['ENCRYPTION_KEY'] = generate_encryption_key()
        print_success("Generated new ENCRYPTION_KEY", timestamp=False)
    
    return config


def setup_plex(existing_config: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Setup and validate Plex configuration."""
    print_header("Step 2: Plex Media Server Configuration")
    
    config = {}
    
    # PLEX_URL
    default_url = existing_config.get('PLEX_URL', 'http://localhost:32400')
    if 'PLEX_URL' in existing_config:
        if prompt_yes_no(f"Keep existing Plex URL ({default_url})?", default=True):
            config['PLEX_URL'] = default_url
            print_success(f"Using existing Plex URL: {default_url}", timestamp=False)
        else:
            default_url = 'http://localhost:32400'
    
    if 'PLEX_URL' not in config:
        config['PLEX_URL'] = prompt_with_default("Enter Plex server URL", default_url)
    
    # PLEX_TOKEN
    print_info("To find your Plex token:")
    print_info("  1. Sign in to your Plex Web App")
    print_info("  2. Browse to a library item and view the XML")
    print_info("  3. Look for 'X-Plex-Token' in the URL")
    print_info("  4. Full instructions: https://support.plex.tv/articles/204059436/")
    
    default_token = existing_config.get('PLEX_TOKEN', '')
    if default_token and prompt_yes_no(f"Keep existing Plex token?", default=True):
        config['PLEX_TOKEN'] = default_token
    else:
        default_token = ''
        config['PLEX_TOKEN'] = prompt_with_default("Enter Plex authentication token", default_token)
    
    # Validate Plex connection
    print_info("Validating Plex connection...", timestamp=False)
    
    def validate_plex(dummy):
        return validate_plex_connection(config['PLEX_URL'], config['PLEX_TOKEN'])
    
    result = prompt_with_validation(
        "Press Enter to validate connection",
        lambda x: validate_plex_connection(config['PLEX_URL'], config['PLEX_TOKEN']),
        default="",
        max_attempts=3
    )
    
    if result is None:
        print_error("Plex validation failed. Please verify your URL and token.")
        return None
    
    return config


def setup_tmdb(existing_config: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Setup and validate TMDB configuration."""
    print_header("Step 3: TMDB API Configuration")
    
    config = {}
    
    print_info("TMDB API key is required for movie/TV show metadata and images.")
    print_info("Get a free API key at: https://www.themoviedb.org/settings/api")
    
    default_key = existing_config.get('TMDB_API_KEY', '')
    if default_key and prompt_yes_no(f"Keep existing TMDB API key?", default=True):
        print_info("Validating TMDB API key...", timestamp=False)
        success, message = validate_tmdb_api_key(default_key)
        if success:
            print_success(message)
            config['TMDB_API_KEY'] = default_key
            return config
        else:
            print_warning(f"Existing key validation failed: {message}")
            print_info("Please enter a new TMDB API key")
    
    api_key = prompt_with_validation(
        "Enter TMDB API key",
        lambda key: validate_tmdb_api_key(key),
        default="",
        max_attempts=3
    )
    
    if api_key is None:
        print_error("TMDB validation failed. Please verify your API key.")
        return None
    
    config['TMDB_API_KEY'] = api_key
    return config


def setup_prowlarr(existing_config: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Setup and validate Prowlarr configuration."""
    print_header("Step 4: Prowlarr Configuration")
    
    config = {}
    
    print_info("Prowlarr is used for torrent indexer search.")
    print_info("Get API key from: Prowlarr → Settings → General → Security → API Key")
    
    # PROWLARR_URL
    default_url = existing_config.get('PROWLARR_URL', 'http://localhost:9696')
    if 'PROWLARR_URL' in existing_config:
        if prompt_yes_no(f"Keep existing Prowlarr URL ({default_url})?", default=True):
            config['PROWLARR_URL'] = default_url
        else:
            default_url = 'http://localhost:9696'
    
    if 'PROWLARR_URL' not in config:
        config['PROWLARR_URL'] = prompt_with_default("Enter Prowlarr URL", default_url)
    
    # PROWLARR_API_KEY
    default_key = existing_config.get('PROWLARR_API_KEY', '')
    if default_key and prompt_yes_no(f"Keep existing Prowlarr API key?", default=True):
        # Validate existing key
        print_info("Validating Prowlarr connection...", timestamp=False)
        success, message = validate_prowlarr_connection(config['PROWLARR_URL'], default_key)
        if success:
            print_success(message)
            config['PROWLARR_API_KEY'] = default_key
            return config
        else:
            print_warning(f"Existing key validation failed: {message}")
            print_info("Please enter a new Prowlarr API key")
    
    api_key = prompt_with_validation(
        "Enter Prowlarr API key",
        lambda key: validate_prowlarr_connection(config['PROWLARR_URL'], key),
        default="",
        max_attempts=3
    )
    
    if api_key is None:
        print_error("Prowlarr validation failed. Please verify your URL and API key.")
        return None
    
    config['PROWLARR_API_KEY'] = api_key
    return config


def setup_qbittorrent(existing_config: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Setup and validate qBittorrent configuration."""
    print_header("Step 5: qBittorrent Configuration")
    
    config = {}
    
    print_info("qBittorrent is used for torrent downloads.")
    
    # QBITTORRENT_URL
    default_url = existing_config.get('QBITTORRENT_URL', 'http://localhost:8080')
    if 'QBITTORRENT_URL' in existing_config:
        if prompt_yes_no(f"Keep existing qBittorrent URL ({default_url})?", default=True):
            config['QBITTORRENT_URL'] = default_url
        else:
            default_url = 'http://localhost:8080'
    
    if 'QBITTORRENT_URL' not in config:
        config['QBITTORRENT_URL'] = prompt_with_default("Enter qBittorrent Web UI URL", default_url)
    
    # QBITTORRENT_USERNAME
    default_username = existing_config.get('QBITTORRENT_USERNAME', 'admin')
    if 'QBITTORRENT_USERNAME' in existing_config:
        if prompt_yes_no(f"Keep existing qBittorrent username ({default_username})?", default=True):
            config['QBITTORRENT_USERNAME'] = default_username
        else:
            default_username = 'admin'
    
    if 'QBITTORRENT_USERNAME' not in config:
        config['QBITTORRENT_USERNAME'] = prompt_with_default("Enter qBittorrent username", default_username)
    
    # QBITTORRENT_PASSWORD
    default_password = existing_config.get('QBITTORRENT_PASSWORD', '')
    has_existing_password = bool(default_password)
    
    if has_existing_password and prompt_yes_no(f"Keep existing qBittorrent password?", default=True):
        # Validate existing credentials
        print_info("Validating qBittorrent connection...", timestamp=False)
        success, message = validate_qbittorrent_connection(
            config['QBITTORRENT_URL'],
            config['QBITTORRENT_USERNAME'],
            default_password
        )
        if success:
            print_success(message)
            config['QBITTORRENT_PASSWORD'] = default_password
            return config
        else:
            print_warning(f"Existing credentials validation failed: {message}")
            print_info("Please enter qBittorrent credentials again")
    
    password = prompt_with_validation(
        "Enter qBittorrent password",
        lambda pwd: validate_qbittorrent_connection(
            config['QBITTORRENT_URL'],
            config['QBITTORRENT_USERNAME'],
            pwd
        ),
        default="",
        max_attempts=3
    )
    
    if password is None:
        print_error("qBittorrent validation failed. Please verify your credentials.")
        return None
    
    config['QBITTORRENT_PASSWORD'] = password
    return config


def setup_paths(existing_config: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Setup and validate file system paths."""
    print_header("Step 6: Media & Download Paths")
    
    config = {}
    
    print_info("These directories must already exist and be writable.")
    print_info("Configure them in qBittorrent and Plex before continuing.")
    
    # DOWNLOADS_PATH
    print_info(f"\n{Colors.BOLD}Downloads Path{Colors.ENDC}", timestamp=False)
    print_info("Where qBittorrent saves completed downloads", timestamp=False)
    
    default_downloads = existing_config.get('DOWNLOADS_PATH', '')
    if default_downloads and prompt_yes_no(f"Keep existing downloads path ({default_downloads})?", default=True):
        success, message = validate_path(default_downloads, "Downloads path")
        if success:
            print_success(message)
            config['DOWNLOADS_PATH'] = default_downloads
        else:
            print_warning(f"Existing path validation failed: {message}")
            default_downloads = ''
    
    if 'DOWNLOADS_PATH' not in config:
        downloads_path = prompt_with_validation(
            "Enter downloads path",
            lambda path: validate_path(path, "Downloads path"),
            default=default_downloads,
            max_attempts=3
        )
        
        if downloads_path is None:
            print_error("Downloads path validation failed.")
            print_error("Please create the directory and ensure it's writable.")
            return None
        
        config['DOWNLOADS_PATH'] = downloads_path
    
    # MOVIES_PATH
    print_info(f"\n{Colors.BOLD}Movies Library Path{Colors.ENDC}", timestamp=False)
    print_info("Where Plex reads movie files", timestamp=False)
    
    default_movies = existing_config.get('MOVIES_PATH', '')
    if default_movies and prompt_yes_no(f"Keep existing movies path ({default_movies})?", default=True):
        success, message = validate_path(default_movies, "Movies path")
        if success:
            print_success(message)
            config['MOVIES_PATH'] = default_movies
        else:
            print_warning(f"Existing path validation failed: {message}")
            default_movies = ''
    
    if 'MOVIES_PATH' not in config:
        movies_path = prompt_with_validation(
            "Enter movies library path",
            lambda path: validate_path(path, "Movies path"),
            default=default_movies,
            max_attempts=3
        )
        
        if movies_path is None:
            print_error("Movies path validation failed.")
            print_error("Please create the directory and ensure it's writable.")
            return None
        
        config['MOVIES_PATH'] = movies_path
    
    # TV_PATH
    print_info(f"\n{Colors.BOLD}TV Shows Library Path{Colors.ENDC}", timestamp=False)
    print_info("Where Plex reads TV show files", timestamp=False)
    
    default_tv = existing_config.get('TV_PATH', '')
    if default_tv and prompt_yes_no(f"Keep existing TV path ({default_tv})?", default=True):
        success, message = validate_path(default_tv, "TV path")
        if success:
            print_success(message)
            config['TV_PATH'] = default_tv
        else:
            print_warning(f"Existing path validation failed: {message}")
            default_tv = ''
    
    if 'TV_PATH' not in config:
        tv_path = prompt_with_validation(
            "Enter TV shows library path",
            lambda path: validate_path(path, "TV path"),
            default=default_tv,
            max_attempts=3
        )
        
        if tv_path is None:
            print_error("TV path validation failed.")
            print_error("Please create the directory and ensure it's writable.")
            return None
        
        config['TV_PATH'] = tv_path
    
    return config


def setup_database(existing_config: Dict[str, str]) -> Dict[str, str]:
    """Setup database configuration."""
    config = {}
    
    # Most users should use default, hide this as advanced
    default_db = existing_config.get('DATABASE_URL', 'sqlite:///./data/plex_manager.db')
    
    if 'DATABASE_URL' in existing_config and existing_config['DATABASE_URL'] != 'sqlite:///./data/plex_manager.db':
        # User has custom database
        if prompt_yes_no(f"Keep existing database configuration?", default=True):
            config['DATABASE_URL'] = default_db
            return config
    
    config['DATABASE_URL'] = 'sqlite:///./data/plex_manager.db'
    return config


def write_env_file(config: Dict[str, str], env_path: Path):
    """Write configuration to .env file."""
    env_content = """# Plex Manager Environment Configuration
# SECURITY: Never commit this file to Git!

# JWT Secret Key (for session tokens)
SECRET_KEY={SECRET_KEY}
JWT_SECRET_KEY={JWT_SECRET_KEY}

# Plex OAuth Client ID (anonymous UUID for development)
PLEX_CLIENT_ID={PLEX_CLIENT_ID}

# Database URL (SQLite by default)
DATABASE_URL={DATABASE_URL}

# Plex Configuration
PLEX_URL={PLEX_URL}
PLEX_TOKEN={PLEX_TOKEN}

# TMDB API Configuration
TMDB_API_KEY={TMDB_API_KEY}

# Encryption Key for Plex tokens (Fernet symmetric encryption)
ENCRYPTION_KEY={ENCRYPTION_KEY}

# qBittorrent Configuration
QBITTORRENT_URL={QBITTORRENT_URL}
QBITTORRENT_USERNAME={QBITTORRENT_USERNAME}
QBITTORRENT_PASSWORD={QBITTORRENT_PASSWORD}

# Prowlarr Configuration (Get API key from: Settings → General → Security → API Key)
PROWLARR_URL={PROWLARR_URL}
PROWLARR_API_KEY={PROWLARR_API_KEY}

# Download & Media Paths (must exist on startup)
DOWNLOADS_PATH={DOWNLOADS_PATH}
MOVIES_PATH={MOVIES_PATH}
TV_PATH={TV_PATH}

# Environment (development or production)
ENV={ENV}
""".format(**config)
    
    with open(env_path, 'w') as f:
        f.write(env_content)


def run_setup_wizard() -> bool:
    """
    Run the interactive setup wizard.
    Returns True if setup was completed successfully, False otherwise.
    """
    print_header("Plex Manager Setup Wizard")
    print_info("Welcome! This wizard will help you configure Plex Manager.", timestamp=False)
    print_info("We'll guide you through each step and validate your configuration.", timestamp=False)
    
    # Create application directories
    print_info("Creating application directories...", timestamp=False)
    ensure_application_directories()
    
    # Parse existing .env if it exists
    env_path = Path('.env')
    existing_config = parse_env_file(env_path)
    
    if existing_config:
        print_info(f"Found existing configuration with {len(existing_config)} values")
        print_info("You can review and update existing values during setup\n")
    
    # Collect all configuration
    all_config = {}
    
    # Step 1: Secrets
    secrets_config = setup_secrets(existing_config)
    all_config.update(secrets_config)
    
    # Step 2: Plex
    plex_config = setup_plex(existing_config)
    if plex_config is None:
        print_error("\nSetup cancelled: Plex configuration failed")
        return False
    all_config.update(plex_config)
    
    # Step 3: TMDB
    tmdb_config = setup_tmdb(existing_config)
    if tmdb_config is None:
        print_error("\nSetup cancelled: TMDB configuration failed")
        return False
    all_config.update(tmdb_config)
    
    # Step 4: Prowlarr
    prowlarr_config = setup_prowlarr(existing_config)
    if prowlarr_config is None:
        print_error("\nSetup cancelled: Prowlarr configuration failed")
        return False
    all_config.update(prowlarr_config)
    
    # Step 5: qBittorrent
    qbittorrent_config = setup_qbittorrent(existing_config)
    if qbittorrent_config is None:
        print_error("\nSetup cancelled: qBittorrent configuration failed")
        return False
    all_config.update(qbittorrent_config)
    
    # Step 6: Paths
    paths_config = setup_paths(existing_config)
    if paths_config is None:
        print_error("\nSetup cancelled: Path configuration failed")
        return False
    all_config.update(paths_config)
    
    # Step 7: Database & Environment
    db_config = setup_database(existing_config)
    all_config.update(db_config)
    all_config['ENV'] = 'development'
    
    # Write .env file
    print_header("Step 7: Saving Configuration")
    print_info("Writing configuration to .env file...", timestamp=False)
    
    try:
        write_env_file(all_config, env_path)
        print_success("Configuration saved successfully!")
    except Exception as e:
        print_error(f"Failed to write .env file: {str(e)}")
        return False
    
    # Success!
    print_header("Setup Complete!")
    print_success("Plex Manager is now configured and ready to use!", timestamp=False)
    print_info("Next steps:", timestamp=False)
    print_info("  1. Start Plex Manager: python main.py", timestamp=False)
    print_info("  2. Open your browser to: http://localhost:8000", timestamp=False)
    print_info("  3. Sign in with your Plex account", timestamp=False)
    print_info("For help and documentation, see: docs/SETUP.md", timestamp=False)
    
    return True


if __name__ == "__main__":
    """Allow running wizard standalone for testing."""
    success = run_setup_wizard()
    sys.exit(0 if success else 1)
