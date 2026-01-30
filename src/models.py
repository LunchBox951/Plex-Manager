"""
Database models for Plex Manager.
Currently implements User model for authentication.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
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
