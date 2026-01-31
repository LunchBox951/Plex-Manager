from plexapi.server import PlexServer
import os
import sys
import time

from media import Movie, TVShow

# Load Plex credentials from environment variables
PLEX_URL = os.getenv('PLEX_URL', '')
PLEX_TOKEN = os.getenv('PLEX_TOKEN', '')

# Check if configuration is set
if not PLEX_URL or not PLEX_TOKEN:
    print("ERROR: Plex configuration not set up!")
    print("Please set PLEX_URL and PLEX_TOKEN in your .env file")
    print("See docs/SETUP.md for detailed instructions.")
    sys.exit(1)

# Login to Plex server
try:
    plex = PlexServer(PLEX_URL, PLEX_TOKEN, timeout=15)
except Exception as e:
    print("ERROR: Could not connect to Plex server!")
    print(f"Details: {e}")
    sys.exit(2)

# Helper functions
def get_plex_server():
    """Returns the connected Plex server instance."""
    return plex

def safe_api_call(api_function, *args, max_retries=3, retry_delay=2, **kwargs):
    """
    Makes a safe API call with retries.
    
    Attempts to execute the provided function. If it fails, it reattempts login to plex and then retries.
    """
    global plex
    
    # Try to execute the API call
    try:
        return api_function(*args, **kwargs)
    except Exception as e:
        print(f"WARNING: Plex API call failed: {e}")
        print(f"Attempting to reconnect and retry (max {max_retries} retries)...")
        
        # Retry with reconnection
        for attempt in range(1, max_retries + 1):
            try:
                print(f"Reconnection attempt {attempt}/{max_retries}...")
                plex = PlexServer(PLEX_URL, PLEX_TOKEN, timeout=15)

                print("Retrying API call...")
                return api_function(*args, **kwargs)
            except Exception as retry_error:
                if attempt < max_retries:
                    print(f"Attempt {attempt} failed: {retry_error}")
                    print(f"Waiting {retry_delay} seconds before next attempt...")
                    time.sleep(retry_delay)
                else:
                    print(f"ERROR: All reconnection attempts failed!")
                    print(f"Details: {retry_error}")
                    sys.exit(2)

def get_plex_libraries():
    """Returns a list of Plex libraries."""
    return safe_api_call(lambda: plex.library.sections())

def get_media_in_libraries(libraries) -> tuple[list[Movie], list[TVShow]]:
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
