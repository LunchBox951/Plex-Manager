"""
Database models for Plex Manager.
Currently implements User model for authentication and Download model for torrent management.
"""

from datetime import datetime, date
from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, Text, Date, Index
from src.database import Base


# Permission bit flags
class Permission:
    """Permission bit flags for user access control."""
    CAN_REQUEST = 1  # Can submit media requests
    ADMIN = 2        # Full system access


class User(Base):
    """
    User model for Plex OAuth authentication.
    Stores encrypted Plex tokens and permission levels.
    """
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    plex_id = Column(String, unique=True, nullable=False, index=True)  # Plex user ID
    username = Column(String, nullable=False)
    email = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    encrypted_plex_token = Column(String, nullable=False)  # Fernet encrypted token
    permissions = Column(Integer, default=Permission.CAN_REQUEST)  # Bitfield
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, default=datetime.utcnow)
    
    def has_permission(self, permission: int) -> bool:
        """Check if user has specific permission."""
        return bool(self.permissions & permission)
    
    def is_admin(self) -> bool:
        """Check if user has admin privileges."""
        return self.has_permission(Permission.ADMIN)
    
    def to_dict(self):
        """Convert user to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "plex_id": self.plex_id,
            "username": self.username,
            "email": self.email,
            "avatar_url": self.avatar_url,
            "permissions": self.permissions,
            "is_admin": self.is_admin(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None
        }


class Download(Base):
    """
    Download model for tracking qBittorrent torrent downloads.
    Stores torrent metadata, progress, status, and file processing information.
    """
    __tablename__ = "downloads"
    
    id = Column(Integer, primary_key=True, index=True)
    torrent_hash = Column(String, unique=True, nullable=False, index=True)  # Info hash from magnet
    magnet_link = Column(Text, nullable=False)  # Full magnet URI
    status = Column(String, nullable=False, default="pending")  # pending, downloading, completed, seeding, failed, partial_failed
    progress = Column(Float, default=0.0)  # 0-100
    seed_ratio = Column(Float, default=0.0)  # Current seed ratio
    target_seed_ratio = Column(Float, default=1.0)  # Target seed ratio before cleanup
    metadata_json = Column(Text, nullable=True)  # JSON string of torrent metadata
    download_path = Column(String, nullable=True)  # Path in downloads directory
    media_type = Column(String, nullable=False)  # movie or tv
    timeout_days = Column(Integer, default=15)  # Days before timeout cleanup
    processed_files_json = Column(Text, nullable=True)  # JSON array of successfully copied files
    failed_reason = Column(String, nullable=True)  # Reason for failure
    
    # Retention system fields
    retention_type = Column(String, nullable=True)  # forever, watch_once, watch_as_released
    protected_from_deletion = Column(Integer, default=0)  # Boolean: 1 = protected, 0 = not protected
    
    # Timestamps
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)  # When download finished
    failed_at = Column(DateTime, nullable=True)  # When marked as failed
    will_timeout_at = Column(DateTime, nullable=True)  # Calculated timeout date
    
    # TMDB metadata for media request tracking
    tmdb_id = Column(Integer, nullable=True, index=True)  # TMDB movie or TV show ID
    year = Column(Integer, nullable=True)  # Release year for matching
    season = Column(Integer, nullable=True)  # For TV shows
    episodes = Column(Text, nullable=True)  # JSON array of requested episode numbers
    
    # Foreign key for media request integration
    media_request_id = Column(Integer, ForeignKey('media_requests.id'), nullable=True, index=True)
    
    # Retry tracking fields
    retry_count = Column(Integer, default=0)  # Number of retry attempts
    torrent_attempt = Column(Integer, default=1)  # Which torrent from scored list (1st, 2nd, 3rd choice)
    next_check_at = Column(DateTime, nullable=True)  # Scheduled time for next retry
    scored_torrents_json = Column(Text, nullable=True)  # JSON array of scored torrents for fallback selection
    
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


class TMDBSeasonCache(Base):
    """
    Cache for TMDB season episode counts.
    Reduces API calls and provides episode count for season pack scoring.
    """
    __tablename__ = "tmdb_season_cache"
    
    id = Column(Integer, primary_key=True, index=True)
    tmdb_id = Column(Integer, nullable=False, index=True)
    season_number = Column(Integer, nullable=False)
    episode_count = Column(Integer, nullable=False)
    season_status = Column(String, nullable=False, default="completed")  # completed or ongoing
    next_episode_air_date = Column(Date, nullable=True)  # For ongoing seasons
    cached_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index('idx_tmdb_season', 'tmdb_id', 'season_number', unique=True),
    )
    
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


class SeasonRequest(Base):
    """
    Tracks specific season/episode requests within a download.
    Enables tracking partial season downloads and episode-level status.
    """
    __tablename__ = "season_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    download_id = Column(Integer, ForeignKey('downloads.id'), nullable=False, index=True)
    season_number = Column(Integer, nullable=False)
    episode_numbers = Column(Text, nullable=True)  # JSON array of episode numbers, null = full season
    status = Column(String, nullable=False, default="pending")  # pending, partial, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
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


class MediaRequest(Base):
    """
    Media request model for tracking user requests with retention policies.
    Supports movies and TV shows with configurable deletion rules.
    """
    __tablename__ = "media_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    tmdb_id = Column(Integer, nullable=False, index=True)  # TMDB movie or TV show ID
    media_type = Column(String, nullable=False)  # movie or tv
    title = Column(String, nullable=False)  # Media title for display
    year = Column(Integer, nullable=True)  # Release year
    
    # Calendar tracking for TV shows
    requested_seasons = Column(Text, nullable=True)  # JSON array of requested season numbers, null = entire show
    track_upcoming = Column(Integer, default=0)  # Boolean: 1 = track future episodes, 0 = don't track
    
    # Retention policy
    retention_type = Column(String, nullable=False, default="watch_once")  # forever, watch_once, watch_as_released
    auto_delete_enabled = Column(Integer, default=1)  # Boolean: 1 = enabled, 0 = disabled
    
    # Watch tracking
    watched_at = Column(DateTime, nullable=True)  # First watch timestamp
    deletion_scheduled_at = Column(DateTime, nullable=True)  # When to delete
    
    # Status tracking
    status = Column(String, nullable=False, default="pending")  # pending, downloading, processing, available, failed, deleted
    
    # Timestamps
    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)  # When media became available
    deleted_at = Column(DateTime, nullable=True)  # When media was deleted
    
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


class EpisodeRetention(Base):
    """
    Episode-level retention overrides for TV shows.
    Allows users to set different retention policies for specific episodes.
    """
    __tablename__ = "episode_retentions"
    
    id = Column(Integer, primary_key=True, index=True)
    media_request_id = Column(Integer, ForeignKey('media_requests.id'), nullable=False, index=True)
    season_number = Column(Integer, nullable=False)
    episode_number = Column(Integer, nullable=False)
    
    # Override retention policy (overrides MediaRequest.retention_type)
    retention_type = Column(String, nullable=False)  # forever, watch_once, watch_as_released
    
    # Episode-specific watch tracking
    watched_at = Column(DateTime, nullable=True)  # When episode was watched
    deletion_scheduled_at = Column(DateTime, nullable=True)  # When to delete episode
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index('idx_episode_retention', 'media_request_id', 'season_number', 'episode_number', unique=True),
    )
    
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


class Settings(Base):
    """
    Key-value settings store for application configuration.
    Enables runtime configuration updates without code changes.
    """
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(String, nullable=False)
    description = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        """Convert setting to dictionary."""
        return {
            "id": self.id,
            "key": self.key,
            "value": self.value,
            "description": self.description,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class TMDBCache(Base):
    """
    TMDB API response cache to minimize API calls.
    Stores search results, trending data, and media details with TTL-based expiration.
    """
    __tablename__ = "tmdb_cache"
    
    id = Column(Integer, primary_key=True, index=True)
    cache_key = Column(String, unique=True, nullable=False, index=True)  # Hash of query params
    cache_type = Column(String, nullable=False, index=True)  # 'search', 'trending', 'details'
    data_json = Column(Text, nullable=False)  # Serialized JSON response
    expires_at = Column(DateTime, nullable=False, index=True)  # TTL expiration
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
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


class SearchCache(Base):
    """
    Per-user search history cache for TMDB searches.
    Links to User for tracking individual search patterns.
    """
    __tablename__ = "search_cache"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    query = Column(String, nullable=False, index=True)  # Normalized search query
    cache_key = Column(String, nullable=False, index=True)  # Reference to TMDBCache
    searched_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        """Convert search cache entry to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "query": self.query,
            "cache_key": self.cache_key,
            "searched_at": self.searched_at.isoformat() if self.searched_at else None
        }

