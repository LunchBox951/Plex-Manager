"""
Pickle-based dataclass models with graceful field defaults.
These replace SQLAlchemy models for non-user data storage.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, Any


@dataclass
class Download:
    """
    Download model for tracking qBittorrent torrent downloads.
    Stores torrent metadata, progress, status, and file processing information.
    """
    id: Optional[int] = None
    torrent_hash: str = ""
    magnet_link: str = ""
    status: str = "pending"
    progress: float = 0.0
    seed_ratio: float = 0.0
    target_seed_ratio: float = 1.0
    metadata_json: Optional[str] = None
    download_path: Optional[str] = None
    media_type: str = ""
    timeout_days: int = 15
    processed_files_json: Optional[str] = None
    failed_reason: Optional[str] = None
    
    # Retention system fields
    retention_type: Optional[str] = None
    protected_from_deletion: int = 0
    
    # Timestamps
    added_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    will_timeout_at: Optional[datetime] = None
    
    # TMDB metadata
    tmdb_id: Optional[int] = None
    year: Optional[int] = None
    season: Optional[int] = None
    episodes: Optional[str] = None
    
    # Foreign key reference
    media_request_id: Optional[int] = None
    
    # Retry tracking
    retry_count: int = 0
    torrent_attempt: int = 1
    next_check_at: Optional[datetime] = None
    scored_torrents_json: Optional[str] = None

    # Upgrade tracking
    is_upgrade: int = 0  # 1 if this download replaces existing lower-quality media
    upgrade_replaces_media_request_id: Optional[int] = None  # MediaRequest ID being upgraded
    
    @classmethod
    def fill_missing_fields(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fill missing fields with defaults or computed values.
        
        Handles status computation based on timestamps and progress.
        """
        # Compute status if missing
        if 'status' not in data:
            if data.get('failed_at'):
                data['status'] = 'failed'
            elif data.get('completed_at'):
                # Check if still seeding vs fully completed
                seed_ratio = data.get('seed_ratio', 0.0)
                target = data.get('target_seed_ratio', 1.0)
                if seed_ratio >= target:
                    data['status'] = 'completed'
                else:
                    data['status'] = 'seeding'
            elif data.get('progress', 0) > 0:
                data['status'] = 'downloading'
            else:
                data['status'] = 'pending'
        
        # Simple defaults
        if 'progress' not in data:
            data['progress'] = 0.0
        if 'seed_ratio' not in data:
            data['seed_ratio'] = 0.0
        if 'target_seed_ratio' not in data:
            data['target_seed_ratio'] = 1.0
        if 'timeout_days' not in data:
            data['timeout_days'] = 15
        if 'protected_from_deletion' not in data:
            data['protected_from_deletion'] = 0
        if 'retry_count' not in data:
            data['retry_count'] = 0
        if 'torrent_attempt' not in data:
            data['torrent_attempt'] = 1
        if 'added_at' not in data:
            data['added_at'] = datetime.utcnow()
        if 'is_upgrade' not in data:
            data['is_upgrade'] = 0
        if 'upgrade_replaces_media_request_id' not in data:
            data['upgrade_replaces_media_request_id'] = None

        return data
    
    def to_dict(self):
        """Convert download to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "torrent_hash": self.torrent_hash,
            "status": self.status,
            "progress": self.progress,
            "seed_ratio": self.seed_ratio,
            "target_seed_ratio": self.target_seed_ratio,
            "media_type": self.media_type,
            "timeout_days": self.timeout_days,
            "tmdb_id": self.tmdb_id,
            "year": self.year,
            "season": self.season,
            "episodes": self.episodes
        }


@dataclass
class MediaRequest:
    """
    Media request model for tracking user requests with retention policies.
    Supports movies and TV shows with configurable deletion rules.
    """
    id: Optional[int] = None
    user_id: int = 0
    tmdb_id: int = 0
    media_type: str = ""
    title: str = ""
    year: Optional[int] = None
    
    # Calendar tracking
    requested_seasons: Optional[str] = None
    track_upcoming: int = 0
    
    # Anime detection (TV shows only)
    is_anime: Optional[bool] = None
    
    # Retention policy
    retention_type: str = "watch_once"
    auto_delete_enabled: int = 1
    
    # Watch tracking
    watched_at: Optional[datetime] = None
    deletion_scheduled_at: Optional[datetime] = None
    
    # Status tracking
    status: str = "pending"
    
    # Timestamps
    requested_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    
    # Library verification
    library_verified_at: Optional[datetime] = None
    library_removed_at: Optional[datetime] = None
    
    @classmethod
    def fill_missing_fields(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Fill missing fields with defaults."""
        if 'status' not in data:
            if data.get('deleted_at'):
                data['status'] = 'deleted'
            elif data.get('completed_at'):
                data['status'] = 'available'
            else:
                data['status'] = 'pending'
        
        if 'retention_type' not in data:
            data['retention_type'] = 'watch_once'
        if 'auto_delete_enabled' not in data:
            data['auto_delete_enabled'] = 1
        if 'track_upcoming' not in data:
            data['track_upcoming'] = 0
        if 'requested_at' not in data:
            data['requested_at'] = datetime.utcnow()
        
        return data
    
    def to_dict(self):
        """Convert media request to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "tmdb_id": self.tmdb_id,
            "media_type": self.media_type,
            "title": self.title,
            "year": self.year,
            "retention_type": self.retention_type,
            "auto_delete_enabled": bool(self.auto_delete_enabled),
            "watched_at": self.watched_at.isoformat() if self.watched_at else None,
            "deletion_scheduled_at": self.deletion_scheduled_at.isoformat() if self.deletion_scheduled_at else None,
            "status": self.status,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None
        }


@dataclass
class TMDBSeasonCache:
    """
    Cache for TMDB season episode counts.
    Reduces API calls and provides episode count for season pack scoring.
    """
    id: Optional[int] = None
    tmdb_id: int = 0
    season_number: int = 0
    episode_count: int = 0
    season_status: str = "completed"
    next_episode_air_date: Optional[date] = None
    cached_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    @classmethod
    def fill_missing_fields(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Fill missing fields with defaults."""
        if 'season_status' not in data:
            data['season_status'] = 'completed'
        if 'cached_at' not in data:
            data['cached_at'] = datetime.utcnow()
        if 'updated_at' not in data:
            data['updated_at'] = datetime.utcnow()
        
        return data
    
    def to_dict(self):
        """Convert cache entry to dictionary."""
        return {
            "id": self.id,
            "tmdb_id": self.tmdb_id,
            "season_number": self.season_number,
            "episode_count": self.episode_count,
            "season_status": self.season_status,
            "next_episode_air_date": self.next_episode_air_date.isoformat() if self.next_episode_air_date else None,
            "cached_at": self.cached_at.isoformat() if self.cached_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


@dataclass
class SeasonRequest:
    """
    Tracks specific season/episode requests within a download.
    Enables tracking partial season downloads and episode-level status.
    """
    id: Optional[int] = None
    download_id: int = 0
    season_number: int = 0
    episode_numbers: Optional[str] = None
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    @classmethod
    def fill_missing_fields(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Fill missing fields with defaults."""
        if 'status' not in data:
            data['status'] = 'pending'
        if 'created_at' not in data:
            data['created_at'] = datetime.utcnow()
        
        return data
    
    def to_dict(self):
        """Convert season request to dictionary."""
        return {
            "id": self.id,
            "download_id": self.download_id,
            "season_number": self.season_number,
            "episode_numbers": self.episode_numbers,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


@dataclass
class EpisodeRetention:
    """
    Episode-level retention overrides for TV shows.
    Allows users to set different retention policies for specific episodes.
    """
    id: Optional[int] = None
    media_request_id: int = 0
    season_number: int = 0
    episode_number: int = 0
    retention_type: str = "watch_once"
    watched_at: Optional[datetime] = None
    deletion_scheduled_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    @classmethod
    def fill_missing_fields(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Fill missing fields with defaults."""
        if 'retention_type' not in data:
            data['retention_type'] = 'watch_once'
        if 'created_at' not in data:
            data['created_at'] = datetime.utcnow()
        
        return data
    
    def to_dict(self):
        """Convert episode retention to dictionary."""
        return {
            "id": self.id,
            "media_request_id": self.media_request_id,
            "season_number": self.season_number,
            "episode_number": self.episode_number,
            "retention_type": self.retention_type,
            "watched_at": self.watched_at.isoformat() if self.watched_at else None,
            "deletion_scheduled_at": self.deletion_scheduled_at.isoformat() if self.deletion_scheduled_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


@dataclass
class TMDBCache:
    """
    TMDB API response cache to minimize API calls.
    Stores search results, trending data, and media details with TTL-based expiration.
    """
    id: Optional[int] = None
    cache_key: str = ""
    cache_type: str = ""
    data_json: str = ""
    expires_at: datetime = field(default_factory=datetime.utcnow)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    @classmethod
    def fill_missing_fields(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Fill missing fields with defaults."""
        if 'created_at' not in data:
            data['created_at'] = datetime.utcnow()
        if 'expires_at' not in data:
            # Default 24 hour expiry if missing
            from datetime import timedelta
            data['expires_at'] = datetime.utcnow() + timedelta(days=1)
        
        return data
    
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return datetime.utcnow() > self.expires_at
    
    def to_dict(self):
        """Convert cache entry to dictionary."""
        return {
            "id": self.id,
            "cache_key": self.cache_key,
            "cache_type": self.cache_type,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


@dataclass
class SearchCache:
    """
    Per-user search history cache for TMDB searches.
    Links to User for tracking individual search patterns.
    """
    id: Optional[int] = None
    user_id: int = 0
    query: str = ""
    cache_key: str = ""
    searched_at: datetime = field(default_factory=datetime.utcnow)
    
    @classmethod
    def fill_missing_fields(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Fill missing fields with defaults."""
        if 'searched_at' not in data:
            data['searched_at'] = datetime.utcnow()
        
        return data
    
    def to_dict(self):
        """Convert search cache entry to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "query": self.query,
            "cache_key": self.cache_key,
            "searched_at": self.searched_at.isoformat() if self.searched_at else None
        }
