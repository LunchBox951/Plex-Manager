from plexapi.server import PlexServer
import os
import json
import sys

from media import Movie, TVShow

# Load Plex credentials from config file
config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'plex.config')

PLEX_URL = ''
PLEX_TOKEN = ''

# Read config file
if os.path.exists(config_path):
    with open(config_path, 'r') as f:
        config = json.load(f)
        PLEX_URL = config.get('plex_url', '')
        PLEX_TOKEN = config.get('plex_token', '')
    
    # Check if config has placeholder values
    if PLEX_URL in ['', 'YOUR_PLEX_URL'] or PLEX_TOKEN in ['', 'YOUR_PLEX_TOKEN']:
        print("ERROR: Plex configuration not set up!")
        print(f"Please edit the config file at: {config_path}")
        print("See docs/SETUP.md for detailed instructions.")
        sys.exit(1)
else:
    # Create placeholder config file
    print(f"Config file not found. Creating placeholder at: {config_path}")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    placeholder_config = {
        "plex_url": "YOUR_PLEX_URL",
        "plex_token": "YOUR_PLEX_TOKEN"
    }
    
    with open(config_path, 'w') as f:
        json.dump(placeholder_config, f, indent=2)
    
    print("\nERROR: Plex configuration required!")
    print(f"A template config file has been created at: {config_path}")
    print("Please edit this file with your Plex server URL and token.")
    print("See docs/SETUP.md for detailed instructions.")
    sys.exit(1)

# Login to Plex server
try:
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
except Exception as e:
    print("ERROR: Could not connect to Plex server!")
    print(f"Details: {e}")
    sys.exit(2)

# Helper functions
def get_plex_server():
    """Returns the connected Plex server instance."""
    return plex

def get_plex_libraries():
    """Returns a list of Plex libraries."""
    return plex.library.sections()

def get_media_in_section(libraries) -> tuple[list[Movie], list[TVShow]]:
    """Returns all media items in the specified library."""
    movies = []
    tv_shows = []

    for library in libraries:
        items = library.all()

        for item in items:
            if library.type == 'movie':
                movies.append(Movie(item))
            elif library.type == 'show':
                tv_shows.append(TVShow(item))

    return movies, tv_shows

