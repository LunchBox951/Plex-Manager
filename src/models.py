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
    
    # Foreign key for future media request integration
    media_request_id = Column(Integer, nullable=True)  # ForeignKey('media_requests.id') when implemented
    
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


class TMDBCache(Base):
    """
    Cache for TMDB season episode counts.
    Reduces API calls and provides episode count for season pack scoring.
    """
    __tablename__ = "tmdb_cache"
    
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
