# Plex Manager - Production Overview

## Project Status: v1.0 Ready

Plex Manager is a unified media request and automation system that replaces the traditional Overseerr → Radarr/Sonarr → Prowlarr/Jackett → qBittorrent stack with a single, integrated application.

## What It Does

**For Users:**
- Netflix-style interface for browsing and requesting movies/TV shows
- One-click requests with automatic download management
- Real-time download progress tracking
- Calendar view for upcoming TV episodes
- Personal watchlist and request history

**For Administrators:**
- Automated media retention system (multi-tier cleanup rules)
- Integrated torrent search via Prowlarr
- Download monitoring and management via qBittorrent
- Background processing with retry logic
- Audit logging for all media operations

## Current Architecture

```
User Interface (HTML/CSS/JS)
         ↓
FastAPI Backend (Python)
         ↓
┌────────┴────────┬─────────────┬──────────────┐
│                 │             │              │
Plex OAuth    TMDB API    Prowlarr API   qBittorrent API
(Login)      (Metadata)  (Torrent Search)  (Downloads)
```

## Implemented Features

### Core Functionality
✅ **Authentication System**
- Plex OAuth integration
- JWT token management
- Encrypted Plex token storage
- First user becomes admin (temporary)

✅ **Media Discovery**
- TMDB integration for search
- Trending movies and TV shows
- Detailed media information pages
- Poster/backdrop image caching

✅ **Request Management**
- Unified request API for movies/TV
- Request status tracking
- Download progress monitoring
- Calendar for upcoming episodes

✅ **Download Automation**
- Prowlarr torrent search integration
- Automated torrent selection (scoring algorithm)
- qBittorrent download management
- Background monitoring with APScheduler
- Retry logic for failed downloads

✅ **Retention System**
- Multi-tier deletion policies
- Configurable retention rules
- Age-based and watch-based cleanup
- Audit logging for deletions

✅ **User Interface**
- Netflix-style homepage with trending content
- Media details pages with request buttons
- Active downloads dashboard
- Calendar view for TV episodes
- Landing page with Plex login

### Technical Implementation
- **Backend**: FastAPI with SQLAlchemy ORM
- **Database**: SQLite with auto-initialization
- **Caching**: Image metadata and poster caching
- **External Services**: Plex, TMDB, Prowlarr, qBittorrent
- **Background Tasks**: APScheduler for download monitoring

## Directory Structure

```
plex-manager/
├── main.py                 # Application entry point
├── requirements.txt        # Python dependencies
├── .env.example           # Environment variable template
├── PLANS.md               # This file - production overview
├── ROADMAP.md             # Development roadmap and future plans
├── src/                   # Application source code
│   ├── main_api.py        # FastAPI application and routes
│   ├── database.py        # Database configuration
│   ├── models.py          # SQLAlchemy models
│   ├── auth.py            # Plex OAuth and JWT
│   ├── TMDB.py            # TMDB API integration
│   ├── prowlarr.py        # Prowlarr torrent search
│   ├── qbittorrent.py     # qBittorrent download management
│   ├── downloads.py       # Download API endpoints
│   ├── download_monitor.py # Background monitoring
│   ├── retention.py       # Retention logic
│   ├── retention_api.py   # Retention API endpoints
│   ├── media.py           # Media utilities
│   ├── plex.py            # Plex integration
│   ├── watchlist.py       # Watchlist management
│   ├── scoring.py         # Torrent scoring algorithm
│   ├── torrent_validator.py # Torrent validation
│   ├── audit.py           # Audit logging
│   └── encryption.py      # Token encryption
├── templates/             # HTML templates
│   ├── landing.html       # Landing/login page
│   ├── homepage.html      # Main dashboard
│   ├── media_details.html # Media details page
│   ├── calendar.html      # TV calendar
│   ├── active_downloads.html # Download status
│   └── base.html          # Base template
├── static/                # CSS, JavaScript, images
│   ├── css/
│   └── img/
├── data/                  # SQLite database storage
│   └── plex_manager.db    # Auto-created on first run
├── cache/                 # TMDB image cache
│   ├── image_metadata.json
│   └── images/
└── docs/                  # Documentation
    └── SETUP.md           # Setup instructions
```

## External Service Dependencies

### Required Services
1. **Plex Media Server** - Media library and OAuth authentication
2. **TMDB API** - Movie/TV metadata and search
3. **Prowlarr** - Torrent indexer aggregation and search
4. **qBittorrent** - Download client with Web UI enabled

### Optional
- Custom download/media paths (configurable via environment variables)

## Configuration

All configuration is handled via environment variables (see `.env.example`):
- JWT secrets for authentication
- Plex OAuth credentials
- TMDB API key
- Prowlarr URL and API key
- qBittorrent connection details
- File system paths for downloads and media

## Version 1.0 Status

**Ready for Production:**
- All core features implemented and functional
- User authentication working
- Media request workflow complete
- Download automation operational
- Retention system active

**Known Limitations:**
- First user automatically becomes admin (proper admin selection system needed)
- SQLite database (sufficient for single-user/small deployments)
- No migration system (database auto-initializes on first run)

## Post-v1.0 Roadmap

See [ROADMAP.md](ROADMAP.md) for detailed future development plans including:
- Proper admin selection/role management system
- Enhanced notification system
- Advanced media management features
- Performance optimizations
- Multi-user scalability improvements
