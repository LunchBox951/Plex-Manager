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
import asyncio
from collections import deque
from datetime import datetime, timedelta, date
from typing import Optional, Dict, List, Any, Tuple

from tmdbv3api import TMDb, Movie, TV, Trending, Season
import requests
import httpx
from filelock import FileLock

from src.console import print_error, print_warning, print_info, print_success, print_monitor


# ============================================================================
# Configuration
# ============================================================================

# Load TMDB API key from environment variable
TMDB_API_KEY = os.environ.get('TMDB_API_KEY', '')

if not TMDB_API_KEY:
    print_error("TMDB API key not configured!")
    print_error("Please set TMDB_API_KEY in your .env file")
    print_error("Get your API key from: https://www.themoviedb.org/settings/api")
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
                print_monitor({"status": "rate_limit", "wait_time": round(wait_time, 2), "message": f"TMDB rate limit reached. Waiting {wait_time:.2f} seconds..."})
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
season_service = Season()
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
        result = api_function(*args, **kwargs)
        return result
    except requests.exceptions.Timeout as e:
        print_monitor({"status": "error", "error_type": "timeout", "message": f"TMDB API timeout: {e}"})
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:  # Rate limit error
            print_monitor({"status": "error", "error_type": "rate_limit", "message": f"TMDB rate limit hit: {e}"})
        else:
            print_monitor({"status": "error", "error_type": "http_error", "message": f"TMDB API HTTP error: {e}"})
    except requests.exceptions.ConnectionError as e:
        print_monitor({"status": "error", "error_type": "connection", "message": f"TMDB API connection error: {e}"})
    except requests.exceptions.RequestException as e:
        print_monitor({"status": "error", "error_type": "network", "message": f"TMDB API network error: {e}"})
    except KeyboardInterrupt:
        print_error("User interrupted the request")
        raise
    except Exception as e:
        print_monitor({"status": "error", "error_type": "unknown", "message": f"TMDB API call failed: {e}"})
    
    # Retry with exponential backoff
    print_monitor({"status": "retrying", "max_retries": max_retries, "message": f"Attempting to retry (max {max_retries} retries)..."})
    
    for attempt in range(1, max_retries + 1):
        try:
            current_delay = retry_delay * (2 ** (attempt - 1))  # Exponential backoff
            print_monitor({"status": "retry_attempt", "attempt": attempt, "max_retries": max_retries, "wait_time": current_delay, "message": f"Retry attempt {attempt}/{max_retries}, waiting {current_delay}s..."})
            time.sleep(current_delay)
            
            # Re-check rate limit
            _rate_limiter.wait_if_needed()
            
            result = api_function(*args, **kwargs)
            return result
        except Exception as retry_error:
            if attempt < max_retries:
                print_monitor({"status": "retry_failed", "attempt": attempt, "error": str(retry_error), "message": f"Attempt {attempt} failed: {retry_error}"})
            else:
                print_error("All retry attempts failed!")
                print_error(f"Details: {retry_error}")
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
        print_info(f"TMDB: Cache hit for movie search: {query}")
        return cached
    
    # Make API call
    print_info(f"TMDB: Searching for movies: {query}")
    if year:
        results = safe_tmdb_call(movie_service.search, query, year=year)
    else:
        results = safe_tmdb_call(movie_service.search, query)
    
    # Validate results (TMDB returns AsObj, not plain list)
    if results is None:
        print_warning(f"TMDB: Returned None for movie search: {query}")
        return []
    
    # Format results
    formatted_results = []
    try:
        for movie in results:
            # Skip invalid items (e.g., strings, None)
            if not hasattr(movie, 'id'):
                print_warning(f"TMDB: Skipping invalid movie result: {type(movie)}")
                continue
                
            try:
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
            except AttributeError as e:
                print_warning(f"TMDB: Error formatting movie result: {e}")
                continue
    except TypeError as e:
        print_warning(f"TMDB: Error iterating movie results: {e}")
        return []
    
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
        print_info(f"TMDB: Cache hit for TV search: {query}")
        return cached
    
    # Make API call
    print_info(f"TMDB: Searching for TV shows: {query}")
    if year:
        results = safe_tmdb_call(tv_service.search, query, first_air_date_year=year)
    else:
        results = safe_tmdb_call(tv_service.search, query)
    
    # Validate results (TMDB returns AsObj, not plain list)
    if results is None:
        print_warning(f"TMDB: Returned None for TV search: {query}")
        return []
    
    # Format results
    formatted_results = []
    try:
        for show in results:
            # Skip invalid items (e.g., strings, None)
            if not hasattr(show, 'id'):
                print_warning(f"TMDB: Skipping invalid TV result: {type(show)}")
                continue
                
            try:
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
            except AttributeError as e:
                print_warning(f"TMDB: Error formatting TV result: {e}")
                continue
    except TypeError as e:
        print_warning(f"TMDB: Error iterating TV results: {e}")
        return []
    
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
        print_info(f"TMDB: Cache hit for movie details: {tmdb_id}")
        return cached
    
    # Make API call
    print_info(f"TMDB: Fetching movie details: {tmdb_id}")
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
        'original_language': movie.original_language if hasattr(movie, 'original_language') else None,
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
        print_info(f"TMDB: Cache hit for TV details: {tmdb_id}")
        return cached
    
    # Make API call
    print_info(f"TMDB: Fetching TV details: {tmdb_id}")
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
        'origin_country': list(show.origin_country) if hasattr(show, 'origin_country') else [],
        'original_language': show.original_language if hasattr(show, 'original_language') else None,
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


def is_anime(tmdb_details: Dict[str, Any]) -> bool:
    """
    Detect if a TV show is anime based on TMDB metadata.
    
    Detection criteria:
    - Primary: Origin country contains 'JP' (Japan)
    - Secondary: Genres include 'Animation'
    
    Args:
        tmdb_details: TV show details from get_tv_details()
        
    Returns:
        True if show is anime, False otherwise
    """
    # Check origin country for Japan
    origin_country = tmdb_details.get('origin_country', [])
    if 'JP' in origin_country:
        # Confirm it's animation genre
        genres = tmdb_details.get('genres', [])
        if 'Animation' in genres:
            return True
    
    return False


def get_trending(media_type: str = 'all', time_window: str = 'week', page: int = 1) -> Dict[str, Any]:
    """
    Get trending movies and TV shows.
    
    Args:
        media_type: Type of media ('all', 'movie', 'tv')
        time_window: Time window ('day' or 'week')
        page: Page number (1-based, default: 1)
        
    Returns:
        Dict with keys:
            - results: List of trending media items
            - page: Current page number
            - total_pages: Total number of pages available
            - total_results: Total number of results
    """
    cache_key = f"trending_{media_type}_{time_window}_page{page}"
    
    # Check global cache (24h TTL)
    cached = _get_global_cache(cache_key, cache_type='trending')
    if cached:
        print_info(f"TMDB: Cache hit for trending: {media_type}/{time_window} page {page}")
        return cached
    
    # Make API call based on media type and time window
    print_info(f"TMDB: Fetching trending: {media_type}/{time_window} page {page}")
    
    if media_type == 'movie':
        if time_window == 'week':
            response = safe_tmdb_call(trending_service.movie_week, page=page)
        else:
            response = safe_tmdb_call(trending_service.movie_day, page=page)
    elif media_type == 'tv':
        if time_window == 'week':
            response = safe_tmdb_call(trending_service.tv_week, page=page)
        else:
            response = safe_tmdb_call(trending_service.tv_day, page=page)
    else:  # all
        if time_window == 'week':
            response = safe_tmdb_call(trending_service.all_week, page=page)
        else:
            response = safe_tmdb_call(trending_service.all_day, page=page)
    
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
    
    # Extract pagination info from response
    result_dict = {
        'results': formatted_results,
        'page': getattr(response, 'page', page),
        'total_pages': getattr(response, 'total_pages', 1),
        'total_results': getattr(response, 'total_results', len(formatted_results))
    }
    
    # Cache results
    _set_global_cache(cache_key, result_dict, cache_type='trending')
    
    return result_dict


# ============================================================================
# Cache Management Functions (for CRON jobs)
# ============================================================================

def refresh_trending_cache():
    """
    Force refresh trending cache.
    
    This should be called by a CRON job in main.py to keep trending data fresh.
    Fetches both week and day trending for all, movies, and TV shows.
    """
    print_info("TMDB: Refreshing trending cache...")
    
    try:
        # Refresh all trending combinations
        get_trending('all', 'week')
        get_trending('all', 'day')
        get_trending('movie', 'week')
        get_trending('movie', 'day')
        get_trending('tv', 'week')
        get_trending('tv', 'day')
        
        print_success("TMDB: Trending cache refreshed successfully")
    except Exception as e:
        print_error(f"Failed to refresh trending cache: {e}")


def clear_user_search_cache(user_id: int):
    """
    Clear all search cache for a specific user.
    
    Args:
        user_id: User ID
        
    TODO: Implement with database in Phase 1
    - DELETE FROM tmdb_cache WHERE user_id = ? AND cache_type = 'search'
    """
    print_info(f"TMDB: Clearing search cache for user {user_id}...")
    # Placeholder - will be implemented with database
    pass


def clear_trending_cache():
    """
    Clear all trending cache entries.
    
    TODO: Implement with database in Phase 1
    - DELETE FROM tmdb_cache WHERE user_id IS NULL AND cache_type = 'trending'
    """
    print_info("TMDB: Clearing trending cache...")
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
    print_info(f"TMDB: Clearing request cache for request {request_id}...")
    # Placeholder - will be implemented with database
    pass


def clear_expired_cache():
    """
    Clear expired cache entries (older than 24 hours).
    
    This should be called by a CRON job in main.py.
    
    TODO: Implement with database in Phase 1
    - DELETE FROM tmdb_cache WHERE cached_at < (now - 24 hours) AND cache_type = 'trending'
    """
    print_info("TMDB: Clearing expired cache entries...")
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
        print_info("TMDB: Validating API key...")
        # Make a simple test request
        safe_tmdb_call(movie_service.popular)
        print_success("TMDB: API key validated successfully")
        return True
    except Exception as e:
        print_error(f"TMDB API key validation failed: {e}")
        return False


# Validate API key on module import
if __name__ != '__main__':
    if not validate_api_key():
        print_warning("TMDB: API key validation failed. Some features may not work.")


# ============================================================================
# Season Caching for Episode Count
# ============================================================================

def get_season_episode_count(
    tmdb_id: int,
    season_number: int
) -> Optional[int]:
    """
    Get episode count for a TV season with intelligent caching.
    
    Caching strategy:
    - Completed seasons: Cached indefinitely
    - Ongoing seasons: Cached with next_episode_air_date, refreshed when date passes
    
    Args:
        tmdb_id: TMDB TV show ID
        season_number: Season number
        
    Returns:
        Episode count or None if failed
        
    Example:
        >>> count = get_season_episode_count(1396, 1)  # Breaking Bad S01
        >>> print(count)  # 7
    """
    from src.pickle_stores import tmdb_season_cache_store
    
    print_info(f"TMDB: Getting episode count for show {tmdb_id} Season {season_number}")
    
    # Check cache first
    index_key = f"{tmdb_id}__{season_number}"
    cache_entry = tmdb_season_cache_store.find_by_index('tmdb_id__season_number', index_key)
    
    current_date = date.today()
    
    if cache_entry:
        # Completed seasons are cached indefinitely
        if cache_entry.season_status == 'completed':
            return cache_entry.episode_count
        
        # Ongoing seasons: check if cache is still valid
        if cache_entry.season_status == 'ongoing':
            if cache_entry.next_episode_air_date and cache_entry.next_episode_air_date > current_date:
                return cache_entry.episode_count
            else:
                print_info("TMDB: Ongoing season cache expired, refreshing...")
    
    # Fetch from TMDB API
    try:
        print_info("TMDB: Fetching season info from API...")
        
        # Use tmdbv3api Season service to get season details
        season_details = safe_tmdb_call(season_service.details, tmdb_id, season_number)
        
        if not season_details or not hasattr(season_details, 'episodes'):
            print_error("TMDB: Failed to get season details")
            return None
        
        episode_count = len(season_details.episodes)
        print_info(f"TMDB: Found {episode_count} episodes")
        
        # Determine season status and next air date
        season_status = 'completed'
        next_episode_air_date = None
        
        # Check if season is ongoing by looking at episode air dates
        for episode in season_details.episodes:
            if hasattr(episode, 'air_date') and episode.air_date:
                try:
                    # Parse air date
                    air_date = datetime.strptime(episode.air_date, '%Y-%m-%d').date()
                    
                    # If any episode airs in the future, season is ongoing
                    if air_date > current_date:
                        season_status = 'ongoing'
                        if next_episode_air_date is None or air_date < next_episode_air_date:
                            next_episode_air_date = air_date
                except Exception as e:
                    print_warning(f"TMDB: Failed to parse air date: {episode.air_date} - {e}")
        
        print_info(f"TMDB: Season status: {season_status}, next air date: {next_episode_air_date}")
        
        # Update or create cache entry
        from src.pickle_models import TMDBSeasonCache as PMTMDBSeasonCache
        if cache_entry:
            cache_entry.episode_count = episode_count
            cache_entry.season_status = season_status
            cache_entry.next_episode_air_date = next_episode_air_date
            cache_entry.updated_at = datetime.utcnow()
        else:
            import uuid
            cache_entry = PMTMDBSeasonCache(
                id=str(uuid.uuid4()),
                tmdb_id=tmdb_id,
                season_number=season_number,
                episode_count=episode_count,
                season_status=season_status,
                next_episode_air_date=next_episode_air_date,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
        
        tmdb_season_cache_store.save(cache_entry)
        print_success(f"TMDB: Cached episode count: {episode_count} (status: {season_status})")
        
        return episode_count
    
    except Exception as e:
        print_error(f"Failed to fetch season info from TMDB: {e}")
        return None


def refresh_ongoing_seasons_cache() -> int:
    """
    Background job to refresh ongoing season caches.
    
    Queries all TMDBCache entries with status='ongoing' and next_episode_air_date <= today,
    then updates their episode counts from TMDB API.
        
    Returns:
        Number of cache entries refreshed
        
    Example (APScheduler integration):
        >>> from apscheduler.schedulers.background import BackgroundScheduler
        >>> scheduler = BackgroundScheduler()
        >>> scheduler.add_job(
        ...     func=refresh_ongoing_seasons_cache,
        ...     trigger='cron',
        ...     hour=2,
        ...     minute=0
        ... )
        >>> scheduler.start()
    """
    from src.pickle_stores import tmdb_season_cache_store
    
    current_date = date.today()
    print_info(f"TMDB: Refreshing ongoing season caches (date: {current_date})")
    
    try:
        # Find ongoing seasons that need refresh
        all_entries = tmdb_season_cache_store.list()
        expired_entries = [
            entry for entry in all_entries
            if entry.season_status == 'ongoing'
            and entry.next_episode_air_date
            and entry.next_episode_air_date <= current_date
        ]
        
        print_info(f"TMDB: Found {len(expired_entries)} ongoing seasons to refresh")
        
        refreshed_count = 0
        for entry in expired_entries:
            try:
                # Fetch updated season info
                season_details = safe_tmdb_call(
                    season_service.details,
                    entry.tmdb_id,
                    entry.season_number
                )
                
                if not season_details or not hasattr(season_details, 'episodes'):
                    print_warning(f"TMDB: Failed to refresh show {entry.tmdb_id} S{entry.season_number}")
                    continue
                
                episode_count = len(season_details.episodes)
                
                # Determine new status
                season_status = 'completed'
                next_episode_air_date = None
                
                for episode in season_details.episodes:
                    if hasattr(episode, 'air_date') and episode.air_date:
                        try:
                            air_date = datetime.strptime(episode.air_date, '%Y-%m-%d').date()
                            if air_date > current_date:
                                season_status = 'ongoing'
                                if next_episode_air_date is None or air_date < next_episode_air_date:
                                    next_episode_air_date = air_date
                        except Exception as e:
                            print_warning(f"TMDB: Failed to parse air date: {e}")
                
                # Update cache
                entry.episode_count = episode_count
                entry.season_status = season_status
                entry.next_episode_air_date = next_episode_air_date
                entry.updated_at = datetime.utcnow()
                
                tmdb_season_cache_store.save(entry)
                
                print_info(f"TMDB: Refreshed show {entry.tmdb_id} S{entry.season_number}: "
                          f"{episode_count} episodes, status: {season_status}")
                
                refreshed_count += 1
                
            except Exception as e:
                print_error(f"Failed to refresh cache entry: {e}")
                continue
        
        print_success(f"TMDB: Successfully refreshed {refreshed_count} ongoing season caches")
        return refreshed_count
    
    except Exception as e:
        print_error(f"Failed to refresh ongoing seasons: {e}")
        return 0


# ============================================================================
# Homepage Caching System for Trending and Search
# ============================================================================

def get_cached_image_path(path: str, size: str = 'w500') -> str:
    """
    Get the cache path for an image without downloading.
    
    Args:
        path: TMDB image path (e.g., '/abc123.jpg')
        size: Image size ('w500' for all images)
        
    Returns:
        Cache path relative to cache directory (e.g., 'w500/abc123.jpg')
    """
    if not path:
        return ''
    
    filename = path.lstrip('/').replace('/', '_')
    return f"{size}/{filename}"


async def download_image(path: str, size: str = 'w500', cache_type: str = 'trending') -> Optional[str]:
    """
    Download TMDB image to local cache directory with async HTTP and retry logic.
    
    Args:
        path: TMDB image path (e.g., '/abc123.jpg')
        size: Image size ('w500' for all images)
        cache_type: 'trending' (7 day TTL) or 'search' (24h TTL)
        
    Returns:
        Local file path relative to cache directory, or None if download fails after 3 retries
    """
    if not path:
        return None
    
    # Ensure cache directory exists
    cache_dir = os.path.join('cache', 'images', size)
    os.makedirs(cache_dir, exist_ok=True)
    
    # Generate filename from path hash
    filename = path.lstrip('/').replace('/', '_')
    file_path = os.path.join(cache_dir, filename)
    
    # Check if file already exists
    if os.path.exists(file_path):
        return f"{size}/{filename}"
    
    # Download image with 300-second timeout (single attempt)
    image_url = f"https://image.tmdb.org/t/p/{size}{path}"
    
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(image_url)
            response.raise_for_status()
            
            # Save to cache
            with open(file_path, 'wb') as f:
                f.write(response.content)
            
            # Update metadata with file locking (60 second timeout)
            metadata_file = os.path.join('cache', 'image_metadata.json')
            lock_file = metadata_file + '.lock'
            lock = FileLock(lock_file, timeout=60)
            
            try:
                with lock:
                    metadata = {}
                    if os.path.exists(metadata_file):
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                    
                    metadata[filename] = {
                        'cache_type': cache_type,
                        'downloaded_at': datetime.utcnow().isoformat(),
                        'path': path,
                        'size': size
                    }
                    
                    with open(metadata_file, 'w') as f:
                        json.dump(metadata, f, indent=2)
            except Exception as lock_error:
                print_warning(f"TMDB: Failed to update metadata for {filename}: {lock_error}")
            
            print_success(f"TMDB: Downloaded image: {filename}")
            return f"{size}/{filename}"
            
    except Exception as e:
        print_error(f"Failed to download image {path} after 300s timeout: {e}")
        return None


async def get_or_fetch_trending(media_type: str, time_window: str = 'week', page: int = 1, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Get trending media from cache or fetch from TMDB API with parallel image downloads.
    
    Args:
        media_type: 'movie' or 'tv'
        time_window: 'day' or 'week'
        page: Page number for pagination
        force_refresh: Bypass cache and fetch fresh data
        
    Returns:
        Dict with 'results', 'page', 'total_pages', 'total_results'
    """
    import hashlib
    from src.pickle_stores import tmdb_cache_store
    
    # Generate cache key with page number
    cache_key = hashlib.md5(f"trending_{media_type}_{time_window}_page{page}".encode()).hexdigest()
    
    # Check database cache if not forcing refresh
    if not force_refresh:
        cache_entry = tmdb_cache_store.load(cache_key)
        
        if cache_entry and cache_entry.expires_at > datetime.utcnow():
            print_info(f"TMDB: Cache hit for trending {media_type} page {page}")
            cached_data = json.loads(cache_entry.data_json)
            
            # Extract results from cached data
            results = cached_data.get('results', []) if isinstance(cached_data, dict) else cached_data
            
            # Verify image files exist and download if missing
            download_tasks = []
            for item in results:
                if item.get('poster_path'):
                    download_tasks.append(download_image(item['poster_path'], 'w500', 'trending'))
                if item.get('backdrop_path'):
                    download_tasks.append(download_image(item['backdrop_path'], 'w500', 'trending'))
            
            if download_tasks:
                await asyncio.gather(*download_tasks, return_exceptions=True)
            
            return cached_data
    
    # Fetch from TMDB API
    print_info(f"TMDB: Fetching trending {media_type} from API page {page}")
    trending_data = get_trending(media_type, time_window, page)
    
    # Extract results list from the dict
    results = trending_data.get('results', []) if isinstance(trending_data, dict) else trending_data
    
    # Collect all download tasks
    download_tasks = []
    for item in results:
        if item.get('poster_path'):
            cached_path = get_cached_image_path(item['poster_path'], 'w500')
            item['poster_url'] = f"/cache-images/{cached_path}"
            download_tasks.append(download_image(item['poster_path'], 'w500', 'trending'))
        
        if item.get('backdrop_path'):
            cached_path = get_cached_image_path(item['backdrop_path'], 'w500')
            item['backdrop_url'] = f"/cache-images/{cached_path}"
            download_tasks.append(download_image(item['backdrop_path'], 'w500', 'trending'))
    
    # Wait for all downloads to complete before returning
    if download_tasks:
        await asyncio.gather(*download_tasks, return_exceptions=True)
    
    # Store in database cache with 7-day TTL
    from src.pickle_models import TMDBCache as PMTMDBCache
    expires_at = datetime.utcnow() + timedelta(days=7)
    
    # Prepare full response data with pagination
    response_data = {
        'results': results,
        'page': trending_data.get('page', page),
        'total_pages': trending_data.get('total_pages', 1),
        'total_results': trending_data.get('total_results', len(results))
    }
    
    # Update or create cache entry
    cache_entry = tmdb_cache_store.load(cache_key)
    if cache_entry:
        cache_entry.data_json = json.dumps(response_data)
        cache_entry.expires_at = expires_at
        cache_entry.created_at = datetime.utcnow()
    else:
        cache_entry = PMTMDBCache(
            id=cache_key,
            cache_key=cache_key,
            cache_type='trending',
            data_json=json.dumps(response_data),
            expires_at=expires_at,
            created_at=datetime.utcnow()
        )
    
    tmdb_cache_store.save(cache_entry)
    print_success(f"TMDB: Cached trending {media_type} page {page} until {expires_at}")
    
    return response_data


async def get_or_fetch_search(query: str, user_id: int, page: int = 1, media_type: str = 'multi') -> Dict[str, Any]:
    """
    Get search results from cache or fetch from TMDB API with parallel image downloads.
    
    Args:
        query: Search query string
        user_id: User ID for search history
        page: Page number (20 results per page)
        media_type: 'movie', 'tv', or 'multi'
        
    Returns:
        Dictionary with 'movies' and 'tv' arrays containing search results
    """
    import hashlib
    from src.pickle_stores import tmdb_cache_store, search_cache_store
    from src.pickle_models import SearchCache as PMSearchCache
    
    # Normalize query
    normalized_query = _normalize_query(query)
    
    # Generate cache key
    cache_key = hashlib.md5(f"search_{normalized_query}_{page}_{media_type}".encode()).hexdigest()
    
    # Check database cache
    cache_entry = tmdb_cache_store.load(cache_key)
    
    if cache_entry and cache_entry.expires_at > datetime.utcnow():
        print_info(f"TMDB: Cache hit for search: {query} (page {page})")
        cached_results = json.loads(cache_entry.data_json)
        
        # Verify image files exist and download if missing
        download_tasks = []
        for media_list in [cached_results.get('movies', {}).get('results', []), cached_results.get('tv', {}).get('results', [])]:
            for item in media_list:
                if item.get('poster_path'):
                    download_tasks.append(download_image(item['poster_path'], 'w500', 'search'))
                if item.get('backdrop_path'):
                    download_tasks.append(download_image(item['backdrop_path'], 'w500', 'search'))
        
        if download_tasks:
            await asyncio.gather(*download_tasks, return_exceptions=True)
        
        # Record search in user history
        import uuid
        search_cache = PMSearchCache(
            id=str(uuid.uuid4()),
            user_id=user_id,
            query=normalized_query,
            cache_key=cache_key,
            searched_at=datetime.utcnow()
        )
        search_cache_store.save(search_cache)
        
        return cached_results
    
    # Fetch from TMDB API
    print_info(f"TMDB: Searching for: {query} (page {page})")
    
    if media_type == 'multi':
        # Search both movies and TV shows
        movies = search_movies(query, user_id) or []
        tv_shows = search_tv(query, user_id) or []
        
        results = {
            'movies': {
                'results': movies[:20] if movies else [],
                'page': page,
                'total_pages': (len(movies) // 20) + 1 if movies else 0,
                'total_results': len(movies) if movies else 0
            },
            'tv': {
                'results': tv_shows[:20] if tv_shows else [],
                'page': page,
                'total_pages': (len(tv_shows) // 20) + 1 if tv_shows else 0,
                'total_results': len(tv_shows) if tv_shows else 0
            }
        }
    elif media_type == 'movie':
        movies = search_movies(query, user_id, page=page) or []
        results = {
            'movies': {
                'results': movies[:20] if movies else [],
                'page': page,
                'total_pages': (len(movies) // 20) + 1 if movies else 0,
                'total_results': len(movies) if movies else 0
            },
            'tv': {'results': [], 'page': 1, 'total_pages': 0, 'total_results': 0}
        }
    else:  # tv
        tv_shows = search_tv(query, user_id, page=page) or []
        results = {
            'movies': {'results': [], 'page': 1, 'total_pages': 0, 'total_results': 0},
            'tv': {
                'results': tv_shows[:20] if tv_shows else [],
                'page': page,
                'total_pages': (len(tv_shows) // 20) + 1 if tv_shows else 0,
                'total_results': len(tv_shows) if tv_shows else 0
            }
        }
    
    # Collect all download tasks
    download_tasks = []
    for media_list in [results['movies']['results'], results['tv']['results']]:
        for item in media_list:
            if item.get('poster_path'):
                cached_path = get_cached_image_path(item['poster_path'], 'w500')
                item['poster_url'] = f"/cache-images/{cached_path}"
                download_tasks.append(download_image(item['poster_path'], 'w500', 'search'))
            
            if item.get('backdrop_path'):
                cached_path = get_cached_image_path(item['backdrop_path'], 'w500')
                item['backdrop_url'] = f"/cache-images/{cached_path}"
                download_tasks.append(download_image(item['backdrop_path'], 'w500', 'search'))
    
    # Wait for all downloads to complete before returning
    if download_tasks:
        await asyncio.gather(*download_tasks, return_exceptions=True)
    
    # Store in database cache with 24-hour TTL
    from src.pickle_models import TMDBCache as PMTMDBCache, SearchCache as PMSearchCache
    import uuid
    
    expires_at = datetime.utcnow() + timedelta(hours=24)
    
    cache_entry = PMTMDBCache(
        id=cache_key,
        cache_key=cache_key,
        cache_type='search',
        data_json=json.dumps(results),
        expires_at=expires_at,
        created_at=datetime.utcnow()
    )
    tmdb_cache_store.save(cache_entry)
    
    # Record in user search history
    search_cache = PMSearchCache(
        id=str(uuid.uuid4()),
        user_id=user_id,
        query=normalized_query,
        cache_key=cache_key,
        searched_at=datetime.utcnow()
    )
    search_cache_store.save(search_cache)
    
    print_success(f"TMDB: Cached search '{query}' until {expires_at}")
    
    return results


