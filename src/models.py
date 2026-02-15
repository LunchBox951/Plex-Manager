"""
Database models for Plex Manager.

SQLite Models (this file):
- User: Authentication and permissions
- Settings: Application configuration
- AuditLog: Action audit trail

Pickle Models (see src/pickle_models.py):
- Download, MediaRequest, TMDBCache, SearchCache
- TMDBSeasonCache, SeasonRequest, EpisodeRetention

Pickle storage provides schema flexibility - new fields can be added without migrations.
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


class AuditLog(Base):
    """
    Audit trail for tracking user actions and system changes.
    Provides accountability and debugging information for retention changes and media requests.
    """
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    action_type = Column(String, nullable=False, index=True)  # 'retention_change', 'request_created', etc.
    entity_type = Column(String, nullable=False)  # 'media_request', 'episode', etc.
    entity_id = Column(Integer, nullable=True, index=True)  # ID of affected entity
    
    # Change tracking
    old_value = Column(Text, nullable=True)  # JSON of old state
    new_value = Column(Text, nullable=True)  # JSON of new state
    description = Column(String, nullable=True)  # Human-readable description
    
    # Context
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    
    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    def to_dict(self):
        """Convert audit log entry to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action_type": self.action_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "description": self.description,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

