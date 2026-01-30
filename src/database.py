"""
Database configuration and session management.
Uses SQLAlchemy with SQLite for user data storage.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Database URL from environment or default to SQLite file
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./plex_manager.db")

# Create SQLAlchemy engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False  # Set to True for SQL query debugging
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Session:
    """
    Dependency for getting database sessions.
    Usage: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database by creating all tables.
    Auto-creates tables based on model definitions.
    
    TODO: Migrate to Alembic migrations before production.
    This approach is suitable for development but doesn't handle
    schema changes, rollbacks, or complex migrations.
    """
    from src.models import Base  # Import here to ensure models are registered
    
    print("Initializing database...")
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully")
