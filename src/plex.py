from plexapi.server import PlexServer
from plexapi.video import Movie, Show
from plexapi.myplex import MyPlexAccount
import os
import sys
import time
import re
from src.console import print_error, print_warning, print_info, print_debug

# Load Plex credentials from environment variables
PLEX_URL = os.getenv('PLEX_URL', '')
PLEX_TOKEN = os.getenv('PLEX_TOKEN', '')

# Check if configuration is set
if not PLEX_URL or not PLEX_TOKEN:
    print_error("Plex configuration not set up!", timestamp=False)
    print_error("Please set PLEX_URL and PLEX_TOKEN in your .env file", timestamp=False)
    print_error("See docs/SETUP.md for detailed instructions.", timestamp=False)
    sys.exit(1)

# Login to Plex server
try:
    plex = PlexServer(PLEX_URL, PLEX_TOKEN, timeout=15)
except Exception as e:
    print_error("Could not connect to Plex server!", timestamp=False)
    print_error(f"Details: {e}", timestamp=False)
    sys.exit(2)

# Helper functions
def get_plex_server():
    """Returns the connected Plex server instance."""
    return plex


def is_plex_server_owner(user_plex_token: str) -> bool:
    """
    Check if the user with the given Plex token owns the configured Plex server.
    
    Args:
        user_plex_token: The user's Plex authentication token
        
    Returns:
        True if the user owns the configured Plex server, False otherwise
        
    Note:
        Returns False if there are any errors (network issues, invalid token, etc.)
        to prevent blocking authentication flow.
    """
    try:
        # Create MyPlexAccount instance for the user
        print_debug(f"[PLEX] Checking server ownership for user token")
        account = MyPlexAccount(token=user_plex_token)
        
        # Get the configured server's machine identifier
        server_machine_id = plex.machineIdentifier
        print_debug(f"[PLEX] Configured server machine ID: {server_machine_id}")
        
        # Query all resources (servers) the user has access to
        resources = account.resources()
        print_debug(f"[PLEX] User has access to {len(resources)} resources")
        
        # Check each resource for ownership
        for resource in resources:
            # Only check Plex Media Server resources
            if resource.product == 'Plex Media Server':
                print_debug(f"[PLEX] Checking server: {resource.name} (ID: {resource.clientIdentifier}, Owned: {resource.owned})")
                
                # Check if this is our configured server and if user owns it
                if resource.clientIdentifier == server_machine_id:
                    if resource.owned:
                        print_info(f"User {account.username} owns the configured Plex server", prefix="PLEX")
                        return True
                    else:
                        print_info(f"User {account.username} has access but does not own the configured Plex server", prefix="PLEX")
                        return False
        
        # Server not found in user's resources
        print_warning(f"[PLEX] Configured server (ID: {server_machine_id}) not found in user's accessible resources")
        return False
        
    except Exception as e:
        # Log error but don't block authentication
        print_error(f"[PLEX] Error checking server ownership: {e}")
        print_error(f"[PLEX] Defaulting to non-admin permissions")
        return False

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
        print_warning(f"[PLEX] Plex API call failed: {e}")
        print_info(f"Attempting to reconnect and retry (max {max_retries} retries)...", prefix="PLEX")
        
        # Retry with reconnection
        for attempt in range(1, max_retries + 1):
            try:
                print_info(f"Reconnection attempt {attempt}/{max_retries}...", prefix="PLEX")
                plex = PlexServer(PLEX_URL, PLEX_TOKEN, timeout=15)

                print_info("Retrying API call...", prefix="PLEX")
                return api_function(*args, **kwargs)
            except Exception as retry_error:
                if attempt < max_retries:
                    print_warning(f"[PLEX] Attempt {attempt} failed: {retry_error}")
                    print_info(f"Waiting {retry_delay} seconds before next attempt...", prefix="PLEX")
                    time.sleep(retry_delay)
                else:
                    print_error(f"[PLEX] All reconnection attempts failed!")
                    print_error(f"[PLEX] Details: {retry_error}")
                    sys.exit(2)

def get_plex_libraries():
    """Returns a list of Plex libraries."""
    return safe_api_call(lambda: plex.library.sections())

def get_media_in_libraries(libraries) -> tuple[list[Movie], list[Show]]:
    """Returns all media items in the specified library."""
    movies = []
    tv_shows = []

    for library in libraries:
        items = library.all()

        for item in items:
            if library.type == 'movie':
                movies.append(Movie(item))
            elif library.type == 'show':
                tv_shows.append(Show(item))

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
    Also returns Plex artwork URLs when media is found.
    
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
            - existing_episodes (list): Episode numbers in Plex (TV only)
            - plex_title (str): Matched title in Plex library
            - plex_poster_url (str): Full URL to Plex poster artwork
            - plex_backdrop_url (str): Full URL to Plex backdrop artwork
            
    Examples:
        # Movie check
        >>> check_media_exists("Inception", 2010, "movie")
        {"exists": True, "plex_title": "Inception", "plex_poster_url": "...", "plex_backdrop_url": "..."}
        
        # TV show - full season
        >>> check_media_exists("Breaking Bad", 2008, "tv", season=1)
        {"exists": True, "partial": False, "plex_title": "Breaking Bad", "existing_episodes": [1,2,3,4,5,6,7]}
        
        # TV show - partial season
        >>> check_media_exists("Breaking Bad", 2008, "tv", season=1, episodes=[1,2,3,4,5,6,7,8,9,10])
        {"exists": True, "partial": True, "missing_episodes": [7,8,9,10], "plex_title": "Breaking Bad"}
    """
    normalized_title = _normalize_title(tmdb_title)
    print_info(f"Checking Plex for: {tmdb_title} ({year}) - {media_type}", prefix="PLEX")
    
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
                if item_year and year:
                    # Ensure both are integers for comparison
                    try:
                        year_int = int(year) if isinstance(year, str) else year
                        if abs(item_year - year_int) > 1:
                            continue
                    except (ValueError, TypeError):
                        # If year conversion fails, skip year check
                        pass
                
                # Match found!
                print_info(f"Found match in Plex: {item.title} ({item_year})", prefix="PLEX")
                
                # Get artwork URLs from Plex
                plex_poster_url = None
                plex_backdrop_url = None
                try:
                    if hasattr(item, 'thumb') and item.thumb:
                        plex_poster_url = plex.url(item.thumb, includeToken=True)
                    if hasattr(item, 'art') and item.art:
                        plex_backdrop_url = plex.url(item.art, includeToken=True)
                except Exception as art_error:
                    print_warning(f"[PLEX] Failed to get Plex artwork URLs: {art_error}")
                
                # For movies, simple existence check
                if media_type == 'movie':
                    return {
                        "exists": True,
                        "plex_title": item.title,
                        "plex_poster_url": plex_poster_url,
                        "plex_backdrop_url": plex_backdrop_url
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
                                "existing_episodes": sorted(existing_episodes),
                                "plex_poster_url": plex_poster_url,
                                "plex_backdrop_url": plex_backdrop_url
                            }
                        
                        # Check which requested episodes are missing
                        requested_set = set(episodes)
                        missing_episodes = sorted(requested_set - existing_episodes)
                        
                        if not missing_episodes:
                            # All episodes exist
                            return {
                                "exists": True,
                                "partial": False,
                                "plex_title": item.title,
                                "existing_episodes": sorted(existing_episodes),
                                "plex_poster_url": plex_poster_url,
                                "plex_backdrop_url": plex_backdrop_url
                            }
                        elif len(missing_episodes) < len(episodes):
                            # Partial match
                            return {
                                "exists": True,
                                "partial": True,
                                "missing_episodes": missing_episodes,
                                "existing_episodes": sorted(existing_episodes),
                                "plex_title": item.title,
                                "plex_poster_url": plex_poster_url,
                                "plex_backdrop_url": plex_backdrop_url
                            }
                        else:
                            # No episodes exist from requested list
                            return {
                                "exists": False,
                                "missing_episodes": episodes
                            }
                    
                    except Exception as e:
                        print_warning(f"[PLEX] Failed to check TV season: {e}")
                        # Season doesn't exist or error occurred
                        return {
                            "exists": False,
                            "missing_episodes": episodes if episodes else []
                        }
                
                # Matched but no season specified for TV
                return {
                    "exists": True,
                    "plex_title": item.title,
                    "plex_poster_url": plex_poster_url,
                    "plex_backdrop_url": plex_backdrop_url
                }
        
        # No match found
        print_info(f"Media not found in Plex: {tmdb_title}", prefix="PLEX")
        return {
            "exists": False,
            "missing_episodes": episodes if episodes else []
        }
    
    except Exception as e:
        print_error(f"[PLEX] Error checking Plex media: {e}")
        # On error, assume doesn't exist to allow request to proceed
        return {
            "exists": False,
            "error": str(e)
        }

