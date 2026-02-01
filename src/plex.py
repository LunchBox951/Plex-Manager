from plexapi.server import PlexServer
import os
import sys
import time
import re
import logging

from media import Movie, TVShow

logger = logging.getLogger(__name__)

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


def _normalize_title(title: str) -> str:
    """
    Normalize title for fuzzy matching.
    
    Removes articles (The, A, An), special characters, and converts to lowercase.
    
    Args:
        title: Original title
        
    Returns:
        Normalized title
    """
    # Remove leading articles
    title = re.sub(r'^(The|A|An)\s+', '', title, flags=re.IGNORECASE)
    
    # Remove special characters
    title = re.sub(r'[:\-\'!?,.]', '', title)
    
    # Normalize whitespace and lowercase
    title = ' '.join(title.split()).lower()
    
    return title


def check_media_exists(
    tmdb_title: str,
    year: int,
    media_type: str,
    season: int = None,
    episodes: list[int] = None
) -> dict:
    """
    Check if media already exists in Plex libraries.
    
    Uses fuzzy title matching (normalized, ±1 year tolerance) to find existing media.
    For TV shows, checks which episodes are present to avoid duplicate downloads.
    
    Args:
        tmdb_title: Canonical title from TMDB
        year: Release year from TMDB
        media_type: 'movie' or 'tv'
        season: Season number (TV only)
        episodes: List of episode numbers (TV only)
        
    Returns:
        dict with keys:
            - exists (bool): Media found in Plex
            - partial (bool): Some but not all episodes exist (TV only)
            - missing_episodes (list): Episode numbers not in Plex (TV only)
            - plex_title (str): Matched title in Plex library
            
    Examples:
        # Movie check
        >>> check_media_exists("Inception", 2010, "movie")
        {"exists": True, "plex_title": "Inception"}
        
        # TV show - full season
        >>> check_media_exists("Breaking Bad", 2008, "tv", season=1)
        {"exists": True, "partial": False, "plex_title": "Breaking Bad"}
        
        # TV show - partial season
        >>> check_media_exists("Breaking Bad", 2008, "tv", season=1, episodes=[1,2,3,4,5,6,7,8,9,10])
        {"exists": True, "partial": True, "missing_episodes": [7,8,9,10], "plex_title": "Breaking Bad"}
    """
    normalized_title = _normalize_title(tmdb_title)
    logger.info(f"Checking Plex for: {tmdb_title} ({year}) - {media_type}")
    
    try:
        libraries = get_plex_libraries()
        
        # Search appropriate libraries
        target_type = 'movie' if media_type == 'movie' else 'show'
        matching_libraries = [lib for lib in libraries if lib.type == target_type]
        
        for library in matching_libraries:
            items = safe_api_call(lambda: library.all())
            
            for item in items:
                # Normalize Plex title for comparison
                plex_title_normalized = _normalize_title(item.title)
                
                # Check title match
                if plex_title_normalized != normalized_title:
                    continue
                
                # Check year match (±1 year tolerance)
                item_year = getattr(item, 'year', None)
                if item_year and abs(item_year - year) > 1:
                    continue
                
                # Match found!
                logger.info(f"Found match in Plex: {item.title} ({item_year})")
                
                # For movies, simple existence check
                if media_type == 'movie':
                    return {
                        "exists": True,
                        "plex_title": item.title
                    }
                
                # For TV shows, check episode availability
                if media_type == 'tv' and season is not None:
                    try:
                        plex_season = item.season(season)
                        existing_episodes = {ep.index for ep in plex_season.episodes()}
                        
                        # If no specific episodes requested, just check season exists
                        if not episodes:
                            return {
                                "exists": True,
                                "partial": False,
                                "plex_title": item.title,
                                "existing_episodes": sorted(existing_episodes)
                            }
                        
                        # Check which requested episodes are missing
                        requested_set = set(episodes)
                        missing_episodes = sorted(requested_set - existing_episodes)
                        
                        if not missing_episodes:
                            # All episodes exist
                            return {
                                "exists": True,
                                "partial": False,
                                "plex_title": item.title
                            }
                        elif len(missing_episodes) < len(episodes):
                            # Partial match
                            return {
                                "exists": True,
                                "partial": True,
                                "missing_episodes": missing_episodes,
                                "plex_title": item.title
                            }
                        else:
                            # No episodes exist from requested list
                            return {
                                "exists": False,
                                "missing_episodes": episodes
                            }
                    
                    except Exception as e:
                        logger.warning(f"Failed to check TV season: {e}")
                        # Season doesn't exist or error occurred
                        return {
                            "exists": False,
                            "missing_episodes": episodes if episodes else []
                        }
                
                # Matched but no season specified for TV
                return {
                    "exists": True,
                    "plex_title": item.title
                }
        
        # No match found
        logger.info(f"Media not found in Plex: {tmdb_title}")
        return {
            "exists": False,
            "missing_episodes": episodes if episodes else []
        }
    
    except Exception as e:
        logger.error(f"Error checking Plex media: {e}")
        # On error, assume doesn't exist to allow request to proceed
        return {
            "exists": False,
            "error": str(e)
        }

