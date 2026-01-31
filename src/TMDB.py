"""
TMDB API Integration Module

Handles all interactions with The Movie Database (TMDB) API including:
- Rate limiting (40 requests per 10 seconds)
- Safe API calls with retry logic
- Database caching for searches, trending, and request metadata
- Query normalization for improved cache hit rates
"""

import os
import sys
import json
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple

from tmdbv3api import TMDb, Movie, TV, Trending
import requests


# ============================================================================
# Configuration
# ============================================================================

# Load TMDB API key from environment variable
TMDB_API_KEY = os.environ.get('TMDB_API_KEY', '')

if not TMDB_API_KEY:
    print("ERROR: TMDB API key not configured!")
    print("Please set TMDB_API_KEY in your .env file")
    print("Get your API key from: https://www.themoviedb.org/settings/api")
    sys.exit(1)


# ============================================================================
# Rate Limiter
# ============================================================================

class TMDBRateLimiter:
    """
    Rate limiter for TMDB API calls.
    
    TMDB limits: 40 requests per 10 seconds
    This class tracks requests and automatically sleeps when approaching the limit.
    """
    
    def __init__(self, max_requests: int = 40, time_window: int = 10):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in time window (default: 40)
            time_window: Time window in seconds (default: 10)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.request_times = deque()
        
    def _check_rate_limit(self):
        """
        Check if we're within rate limits. Sleep if necessary.
        
        Removes timestamps older than time_window and sleeps if at limit.
        """
        current_time = time.time()
        
        # Remove timestamps older than our time window
        while self.request_times and (current_time - self.request_times[0]) > self.time_window:
            self.request_times.popleft()
        
        # If at limit, calculate wait time and sleep
        if len(self.request_times) >= self.max_requests:
            oldest_request = self.request_times[0]
            wait_time = self.time_window - (current_time - oldest_request) + 0.1  # Add buffer
            
            if wait_time > 0:
                print(f"Rate limit reached. Waiting {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                # Recursively check again after waiting
                self._check_rate_limit()
        
        # Record this request
        self.request_times.append(current_time)
    
    def wait_if_needed(self):
        """Public method to check rate limit before making request."""
        self._check_rate_limit()


# Initialize global rate limiter
_rate_limiter = TMDBRateLimiter()


# ============================================================================
# TMDB Client Initialization
# ============================================================================

# Initialize TMDB client
tmdb = TMDb()
tmdb.api_key = TMDB_API_KEY
tmdb.language = 'en'
tmdb.REQUESTS_TIMEOUT = 10  # Set 10 second timeout for all requests

# Initialize TMDB service objects
movie_service = Movie()
tv_service = TV()
trending_service = Trending()


# ============================================================================
# Safe API Call Wrapper
# ============================================================================

def safe_tmdb_call(api_function, *args, max_retries: int = 3, retry_delay: int = 2, **kwargs):
    """
    Makes a safe TMDB API call with rate limiting and retries.
    
    Args:
        api_function: Function to call
        *args: Arguments to pass to function
        max_retries: Maximum retry attempts (default: 3)
        retry_delay: Initial delay between retries in seconds (default: 2)
        **kwargs: Keyword arguments to pass to function
        
    Returns:
        Result from api_function
        
    Raises:
        SystemExit: If all retries fail
    """
    # Check rate limit before attempting
    _rate_limiter.wait_if_needed()
    
    # Try to execute the API call
    try:
        return api_function(*args, **kwargs)
    except requests.exceptions.Timeout as e:
        print(f"WARNING: TMDB API timeout: {e}")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:  # Rate limit error
            print(f"WARNING: TMDB rate limit hit: {e}")
        else:
            print(f"WARNING: TMDB API HTTP error: {e}")
    except requests.exceptions.ConnectionError as e:
        print(f"WARNING: TMDB API connection error: {e}")
    except requests.exceptions.RequestException as e:
        print(f"WARNING: TMDB API network error: {e}")
    except KeyboardInterrupt:
        print("\nERROR: User interrupted the request")
        raise
    except Exception as e:
        print(f"WARNING: TMDB API call failed: {e}")
    
    # Retry with exponential backoff
    print(f"Attempting to retry (max {max_retries} retries)...")
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"Retry attempt {attempt}/{max_retries}...")
            current_delay = retry_delay * (2 ** (attempt - 1))  # Exponential backoff
            print(f"Waiting {current_delay} seconds before retry...")
            time.sleep(current_delay)
            
            # Re-check rate limit
            _rate_limiter.wait_if_needed()
            
            print("Retrying API call...")
            return api_function(*args, **kwargs)
        except Exception as retry_error:
            if attempt < max_retries:
                print(f"Attempt {attempt} failed: {retry_error}")
            else:
                print(f"ERROR: All retry attempts failed!")
                print(f"Details: {retry_error}")
                raise


# ============================================================================
# Cache Utilities
# ============================================================================

# NOTE: Database implementation will be added in Phase 1
# For now, these are placeholder functions that will be replaced with actual DB calls

def _normalize_query(query: str) -> str:
    """
    Normalize search query for better cache hit rates.
    
    Args:
        query: Raw search query
        
    Returns:
        Normalized query (lowercase, trimmed, single spaces)
    """
    return ' '.join(query.lower().strip().split())


def _get_user_search_cache(user_id: int, query: str) -> Optional[List[Dict]]:
    """
    Retrieve cached search results for a user.
    
    Args:
        user_id: User ID
        query: Search query (will be normalized)
        
    Returns:
        Cached search results or None if not found
        
    TODO: Implement with database in Phase 1
    """
    # Placeholder - will be implemented with database
    return None


def _set_user_search_cache(user_id: int, query: str, results: List[Dict]):
    """
    Cache search results for a user (max 10 per user, FIFO eviction).
    
    Args:
        user_id: User ID
        query: Search query (will be normalized)
        results: Search results to cache
        
    TODO: Implement with database in Phase 1
    - Query tmdb_cache table for user's search entries
    - If count >= 10, delete oldest by cached_at
    - Insert new cache entry
    """
    # Placeholder - will be implemented with database
    pass


def _get_global_cache(cache_key: str, cache_type: str = 'trending') -> Optional[Dict]:
    """
    Retrieve global cached data (trending, request metadata).
    
    Args:
        cache_key: Cache key identifier
        cache_type: Type of cache ('trending' or 'request')
        
    Returns:
        Cached data or None if not found/expired
        
    TODO: Implement with database in Phase 1
    - Query tmdb_cache WHERE user_id IS NULL AND cache_key = ? AND cache_type = ?
    - Check if cached_at + 24h > now (TTL check)
    - Return data_json or None
    """
    # Placeholder - will be implemented with database
    return None


def _set_global_cache(cache_key: str, data: Dict, cache_type: str = 'trending'):
    """
    Store global cached data (trending, request metadata).
    
    Args:
        cache_key: Cache key identifier
        data: Data to cache
        cache_type: Type of cache ('trending' or 'request')
        
    TODO: Implement with database in Phase 1
    - INSERT OR REPLACE into tmdb_cache
    - Set user_id = NULL, cache_type, cache_key, data_json, cached_at = now
    """
    # Placeholder - will be implemented with database
    pass


# ============================================================================
# Core TMDB Functions
# ============================================================================

def search_movies(query: str, user_id: int, year: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Search for movies by title.
    
    Args:
        query: Movie title to search for
        user_id: User ID for cache management
        year: Optional year to filter results
        
    Returns:
        List of movie results with keys:
            - id: TMDB ID
            - title: Movie title
            - release_date: Release date (YYYY-MM-DD)
            - year: Release year
            - overview: Movie description
            - poster_path: Poster image path
            - backdrop_path: Backdrop image path
            - vote_average: Rating (0-10)
    """
    normalized_query = _normalize_query(query)
    cache_key = f"{normalized_query}_{year}" if year else normalized_query
    
    # Check user's search cache
    cached = _get_user_search_cache(user_id, cache_key)
    if cached:
        print(f"Cache hit for movie search: {query}")
        return cached
    
    # Make API call
    print(f"Searching TMDB for movies: {query}")
    if year:
        results = safe_tmdb_call(movie_service.search, query, year=year)
    else:
        results = safe_tmdb_call(movie_service.search, query)
    
    # Format results
    formatted_results = []
    for movie in results:
        formatted_results.append({
            'id': movie.id,
            'title': movie.title,
            'release_date': movie.release_date,
            'year': movie.release_date[:4] if movie.release_date else None,
            'overview': movie.overview,
            'poster_path': movie.poster_path,
            'backdrop_path': movie.backdrop_path,
            'vote_average': movie.vote_average,
        })
    
    # Cache results
    _set_user_search_cache(user_id, cache_key, formatted_results)
    
    return formatted_results


def search_tv(query: str, user_id: int, year: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Search for TV shows by title.
    
    Args:
        query: TV show title to search for
        user_id: User ID for cache management
        year: Optional year to filter results
        
    Returns:
        List of TV show results with keys:
            - id: TMDB ID
            - name: Show name
            - first_air_date: First air date (YYYY-MM-DD)
            - year: First air year
            - overview: Show description
            - poster_path: Poster image path
            - backdrop_path: Backdrop image path
            - vote_average: Rating (0-10)
    """
    normalized_query = _normalize_query(query)
    cache_key = f"tv_{normalized_query}_{year}" if year else f"tv_{normalized_query}"
    
    # Check user's search cache
    cached = _get_user_search_cache(user_id, cache_key)
    if cached:
        print(f"Cache hit for TV search: {query}")
        return cached
    
    # Make API call
    print(f"Searching TMDB for TV shows: {query}")
    if year:
        results = safe_tmdb_call(tv_service.search, query, first_air_date_year=year)
    else:
        results = safe_tmdb_call(tv_service.search, query)
    
    # Format results
    formatted_results = []
    for show in results:
        formatted_results.append({
            'id': show.id,
            'name': show.name,
            'first_air_date': show.first_air_date,
            'year': show.first_air_date[:4] if show.first_air_date else None,
            'overview': show.overview,
            'poster_path': show.poster_path,
            'backdrop_path': show.backdrop_path,
            'vote_average': show.vote_average,
        })
    
    # Cache results
    _set_user_search_cache(user_id, cache_key, formatted_results)
    
    return formatted_results


def get_movie_details(tmdb_id: int) -> Dict[str, Any]:
    """
    Get detailed information for a specific movie.
    
    Args:
        tmdb_id: TMDB movie ID
        
    Returns:
        Movie details with keys:
            - id: TMDB ID
            - title: Movie title
            - release_date: Release date (YYYY-MM-DD)
            - year: Release year
            - runtime: Runtime in minutes
            - overview: Movie description
            - poster_path: Poster image path
            - backdrop_path: Backdrop image path
            - vote_average: Rating (0-10)
            - genres: List of genre names
            - tagline: Movie tagline
    """
    cache_key = f"movie_{tmdb_id}"
    
    # Check global cache (used for requested media)
    cached = _get_global_cache(cache_key, cache_type='request')
    if cached:
        print(f"Cache hit for movie details: {tmdb_id}")
        return cached
    
    # Make API call
    print(f"Fetching movie details from TMDB: {tmdb_id}")
    movie = safe_tmdb_call(movie_service.details, tmdb_id)
    
    # Format result
    details = {
        'id': movie.id,
        'title': movie.title,
        'release_date': movie.release_date,
        'year': movie.release_date[:4] if movie.release_date else None,
        'runtime': movie.runtime,
        'overview': movie.overview,
        'poster_path': movie.poster_path,
        'backdrop_path': movie.backdrop_path,
        'vote_average': movie.vote_average,
        'genres': [genre['name'] for genre in movie.genres] if movie.genres else [],
        'tagline': movie.tagline,
    }
    
    # Cache for future requests
    _set_global_cache(cache_key, details, cache_type='request')
    
    return details


def get_tv_details(tmdb_id: int) -> Dict[str, Any]:
    """
    Get detailed information for a specific TV show.
    
    Args:
        tmdb_id: TMDB TV show ID
        
    Returns:
        TV show details with keys:
            - id: TMDB ID
            - name: Show name
            - first_air_date: First air date (YYYY-MM-DD)
            - year: First air year
            - number_of_seasons: Total seasons
            - number_of_episodes: Total episodes
            - overview: Show description
            - poster_path: Poster image path
            - backdrop_path: Backdrop image path
            - vote_average: Rating (0-10)
            - genres: List of genre names
            - seasons: List of season info
    """
    cache_key = f"tv_{tmdb_id}"
    
    # Check global cache (used for requested media)
    cached = _get_global_cache(cache_key, cache_type='request')
    if cached:
        print(f"Cache hit for TV details: {tmdb_id}")
        return cached
    
    # Make API call
    print(f"Fetching TV details from TMDB: {tmdb_id}")
    show = safe_tmdb_call(tv_service.details, tmdb_id)
    
    # Format result
    details = {
        'id': show.id,
        'name': show.name,
        'first_air_date': show.first_air_date,
        'year': show.first_air_date[:4] if show.first_air_date else None,
        'number_of_seasons': show.number_of_seasons,
        'number_of_episodes': show.number_of_episodes,
        'overview': show.overview,
        'poster_path': show.poster_path,
        'backdrop_path': show.backdrop_path,
        'vote_average': show.vote_average,
        'genres': [genre['name'] for genre in show.genres] if show.genres else [],
        'seasons': [
            {
                'season_number': season['season_number'],
                'episode_count': season['episode_count'],
                'air_date': season.get('air_date'),
            }
            for season in show.seasons
        ] if show.seasons else [],
    }
    
    # Cache for future requests
    _set_global_cache(cache_key, details, cache_type='request')
    
    return details


def get_trending(media_type: str = 'all', time_window: str = 'week') -> List[Dict[str, Any]]:
    """
    Get trending movies and TV shows.
    
    Args:
        media_type: Type of media ('all', 'movie', 'tv')
        time_window: Time window ('day' or 'week')
        
    Returns:
        List of trending media with keys:
            - id: TMDB ID
            - title/name: Media title
            - media_type: 'movie' or 'tv'
            - release_date/first_air_date: Release date
            - overview: Description
            - poster_path: Poster image path
            - backdrop_path: Backdrop image path
            - vote_average: Rating (0-10)
    """
    cache_key = f"trending_{media_type}_{time_window}"
    
    # Check global cache (24h TTL)
    cached = _get_global_cache(cache_key, cache_type='trending')
    if cached:
        print(f"Cache hit for trending: {media_type}/{time_window}")
        return cached
    
    # Make API call based on media type and time window
    print(f"Fetching trending from TMDB: {media_type}/{time_window}")
    
    if media_type == 'movie':
        if time_window == 'week':
            response = safe_tmdb_call(trending_service.movie_week)
        else:
            response = safe_tmdb_call(trending_service.movie_day)
    elif media_type == 'tv':
        if time_window == 'week':
            response = safe_tmdb_call(trending_service.tv_week)
        else:
            response = safe_tmdb_call(trending_service.tv_day)
    else:  # all
        if time_window == 'week':
            response = safe_tmdb_call(trending_service.all_week)
        else:
            response = safe_tmdb_call(trending_service.all_day)
    
    # Extract results from response
    results = response.results if hasattr(response, 'results') else response
    
    # Format results
    formatted_results = []
    for item in results:
        result = {
            'id': item.id,
            'media_type': getattr(item, 'media_type', media_type),
            'overview': getattr(item, 'overview', ''),
            'poster_path': getattr(item, 'poster_path', None),
            'backdrop_path': getattr(item, 'backdrop_path', None),
            'vote_average': getattr(item, 'vote_average', 0),
        }
        
        # Add type-specific fields based on what attributes exist
        if hasattr(item, 'title'):  # Movie
            result['title'] = item.title
            result['release_date'] = getattr(item, 'release_date', None)
            if not result.get('media_type'):
                result['media_type'] = 'movie'
        elif hasattr(item, 'name'):  # TV
            result['name'] = item.name
            result['first_air_date'] = getattr(item, 'first_air_date', None)
            if not result.get('media_type'):
                result['media_type'] = 'tv'
        
        formatted_results.append(result)
    
    # Cache results
    _set_global_cache(cache_key, formatted_results, cache_type='trending')
    
    return formatted_results


# ============================================================================
# Cache Management Functions (for CRON jobs)
# ============================================================================

def refresh_trending_cache():
    """
    Force refresh trending cache.
    
    This should be called by a CRON job in main.py to keep trending data fresh.
    Fetches both week and day trending for all, movies, and TV shows.
    """
    print("Refreshing trending cache...")
    
    try:
        # Refresh all trending combinations
        get_trending('all', 'week')
        get_trending('all', 'day')
        get_trending('movie', 'week')
        get_trending('movie', 'day')
        get_trending('tv', 'week')
        get_trending('tv', 'day')
        
        print("Trending cache refreshed successfully")
    except Exception as e:
        print(f"ERROR: Failed to refresh trending cache: {e}")


def clear_user_search_cache(user_id: int):
    """
    Clear all search cache for a specific user.
    
    Args:
        user_id: User ID
        
    TODO: Implement with database in Phase 1
    - DELETE FROM tmdb_cache WHERE user_id = ? AND cache_type = 'search'
    """
    print(f"Clearing search cache for user {user_id}...")
    # Placeholder - will be implemented with database
    pass


def clear_trending_cache():
    """
    Clear all trending cache entries.
    
    TODO: Implement with database in Phase 1
    - DELETE FROM tmdb_cache WHERE user_id IS NULL AND cache_type = 'trending'
    """
    print("Clearing trending cache...")
    # Placeholder - will be implemented with database
    pass


def clear_request_cache(request_id: int):
    """
    Clear cached metadata for a specific request.
    
    This should be called when media is deleted from Plex.
    
    Args:
        request_id: Request ID
        
    TODO: Implement with database in Phase 1
    - Get tmdb_id from media_requests table
    - DELETE FROM tmdb_cache WHERE cache_key = 'movie_{tmdb_id}' OR 'tv_{tmdb_id}'
    """
    print(f"Clearing request cache for request {request_id}...")
    # Placeholder - will be implemented with database
    pass


def clear_expired_cache():
    """
    Clear expired cache entries (older than 24 hours).
    
    This should be called by a CRON job in main.py.
    
    TODO: Implement with database in Phase 1
    - DELETE FROM tmdb_cache WHERE cached_at < (now - 24 hours) AND cache_type = 'trending'
    """
    print("Clearing expired cache entries...")
    # Placeholder - will be implemented with database
    pass


# ============================================================================
# Initialization & Validation
# ============================================================================

def validate_api_key() -> bool:
    """
    Validate TMDB API key with a test request.
    
    Returns:
        True if API key is valid, False otherwise
    """
    try:
        print("Validating TMDB API key...")
        # Make a simple test request
        safe_tmdb_call(movie_service.popular)
        print("TMDB API key validated successfully")
        return True
    except Exception as e:
        print(f"ERROR: TMDB API key validation failed: {e}")
        return False


# Validate API key on module import
if __name__ != '__main__':
    if not validate_api_key():
        print("WARNING: TMDB API key validation failed. Some features may not work.")
