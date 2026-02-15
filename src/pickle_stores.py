"""
Global pickle store instances for easy access throughout the application.
"""

from src.pickle_storage import PickleStore
from src.pickle_models import (
    Download,
    MediaRequest,
    TMDBCache,
    SearchCache,
    TMDBSeasonCache,
    SeasonRequest,
    EpisodeRetention
)

# Initialize store instances
# Data stores (application data in /data)
download_store = PickleStore('data/downloads', Download)
media_request_store = PickleStore('data/media_requests', MediaRequest)
season_request_store = PickleStore('data/season_requests', SeasonRequest)
episode_retention_store = PickleStore('data/episode_retentions', EpisodeRetention)

# Cache stores (temporary data in /cache)
tmdb_cache_store = PickleStore('cache/tmdb_cache', TMDBCache)
search_cache_store = PickleStore('cache/search_cache', SearchCache)
tmdb_season_cache_store = PickleStore('cache/tmdb_season_cache', TMDBSeasonCache)

# Register indexes for each store
def register_all_indexes():
    """Register all indexes for fast lookups."""
    # Download indexes
    download_store.register_index('torrent_hash')
    download_store.register_index('status')
    download_store.register_index('media_request_id')
    
    # MediaRequest indexes
    media_request_store.register_index('user_id')
    media_request_store.register_index('tmdb_id__media_type')  # Composite: (tmdb_id, media_type) - use __ as delimiter
    media_request_store.register_index('status')
    
    # TMDBCache indexes
    tmdb_cache_store.register_index('cache_key')
    tmdb_cache_store.register_index('cache_type')
    
    # SearchCache indexes
    search_cache_store.register_index('user_id')
    
    # TMDBSeasonCache indexes
    tmdb_season_cache_store.register_index('tmdb_id__season_number')  # Composite: (tmdb_id, season_number) - use __ as delimiter
    tmdb_season_cache_store.register_index('season_status')
    
    # SeasonRequest indexes
    season_request_store.register_index('download_id')
    
    # EpisodeRetention indexes
    episode_retention_store.register_index('media_request_id')
    episode_retention_store.register_index('media_request_id__season_number__episode_number')  # Composite - use __ as delimiter


# Call on module import
register_all_indexes()
