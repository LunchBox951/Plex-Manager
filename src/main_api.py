"""
FastAPI application configuration and main entry point.
Handles routing, middleware, and application lifecycle.
"""

import os
import logging
import datetime
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session

from src.database import init_db, get_db
from src.auth import router as auth_router, get_current_user
from src.downloads import router as downloads_router
from src.retention_api import router as retention_router
from src.download_monitor import start_monitor, stop_monitor
from src.models import User, MediaRequest, Download

# Configure logging to show INFO and above
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# Validate required environment variables
def validate_environment():
    """Validate that all required environment variables are set."""
    required_vars = [
        'PLEX_URL',
        'ENCRYPTION_KEY',
        'JWT_SECRET_KEY',
        'DOWNLOADS_PATH',
        'MOVIES_PATH',
        'TV_PATH',
        'QBITTORRENT_URL',
        'QBITTORRENT_USERNAME',
        'QBITTORRENT_PASSWORD'
    ]
    
    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    
    # Verify paths exist
    paths_to_check = {
        'DOWNLOADS_PATH': os.getenv('DOWNLOADS_PATH'),
        'MOVIES_PATH': os.getenv('MOVIES_PATH'),
        'TV_PATH': os.getenv('TV_PATH')
    }
    
    missing_paths = []
    for name, path in paths_to_check.items():
        if path and not os.path.exists(path):
            missing_paths.append(f"{name}: {path}")
    
    if missing_paths:
        raise ValueError(f"Required paths do not exist:\n" + "\n".join(missing_paths))
    
    print("✓ All environment variables validated")
    print(f"✓ Downloads path: {os.getenv('DOWNLOADS_PATH')}")
    print(f"✓ Movies path: {os.getenv('MOVIES_PATH')}")
    print(f"✓ TV path: {os.getenv('TV_PATH')}")


# Application lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    # Startup
    print("Starting Plex Manager API...")
    
    # Validate environment
    validate_environment()
    
    # Initialize database
    init_db()
    
    # Start download monitor
    start_monitor()
    
    print("API ready!")
    
    yield
    
    # Shutdown
    print("Shutting down Plex Manager API...")
    stop_monitor()
    print("Shutdown complete")


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="Plex Manager",
    description="Unified media request and automation system",
    version="0.1.0",
    lifespan=lifespan
)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/cache-images", StaticFiles(directory="cache/images"), name="cache")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Include routers
app.include_router(auth_router)
app.include_router(downloads_router, prefix="/api", tags=["downloads"])
app.include_router(retention_router)


# Root route - Landing page
@app.get("/", response_class=HTMLResponse)
@limiter.limit("100/minute")
async def landing_page(request: Request):
    """
    Serve landing page or redirect to dashboard if already authenticated.
    """
    # Check if user is authenticated
    try:
        token = request.cookies.get("session_token")
        if token:
            # Try to validate token
            from src.database import SessionLocal
            db = SessionLocal()
            try:
                user = await get_current_user(request, db)
                if user:
                    return RedirectResponse(url="/home", status_code=302)
            except:
                pass
            finally:
                db.close()
    except:
        pass
    
    return templates.TemplateResponse("landing.html", {"request": request})


# Health check endpoint
@app.get("/api/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "Plex Manager API",
        "version": "0.1.0"
    }


# ============================================================================
# Homepage API Endpoints
# ============================================================================

@app.get("/home", response_class=HTMLResponse)
async def home_page(request: Request, db: Session = Depends(get_db)):
    """Serve Netflix-style homepage (replaces dashboard)."""
    try:
        # Get current user using the standard authentication
        user = await get_current_user(request, db)
        
        # Render homepage template
        return templates.TemplateResponse(
            "homepage.html",
            {"request": request, "user": user, "current_page": "home"}
        )
    except Exception as e:
        print(f"Homepage access failed: {e}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(url="/", status_code=302)


@app.get("/api/trending/movies")
async def api_trending_movies(
    time_window: str = "week",
    page: int = 1,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get trending movies from TMDB with Plex library status and pagination."""
    from src.TMDB import get_trending, download_image
    from src.plex import check_media_exists
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Get trending data with pagination
        trending_data = get_trending('movie', time_window, page)
        results = trending_data.get('results', [])
        
        # Download and cache images for each movie
        for item in results:
            if item.get('poster_path'):
                cached_path = download_image(item['poster_path'], 'w500', 'trending')
                if cached_path:
                    item['poster_url'] = f"/cache-images/{cached_path}"
            
            if item.get('backdrop_path'):
                cached_path = download_image(item['backdrop_path'], 'w500', 'trending')
                if cached_path:
                    item['backdrop_url'] = f"/cache-images/{cached_path}"
        
        # Check Plex library status for each movie
        try:
            for item in results:
                title = item.get('title', '')
                year = item.get('year')
                
                # Check if in Plex library
                plex_check = check_media_exists(title, year, 'movie')
                item['in_library'] = plex_check.get('exists', False)
                item['plex_title'] = plex_check.get('plex_title', '')
        except Exception as e:
            logger.warning(f"Failed to check Plex library: {e}")
            # Continue without library status
            for item in results:
                item['in_library'] = False
        
        return {
            "results": results,
            "time_window": time_window,
            "page": trending_data.get('page', page),
            "total_pages": trending_data.get('total_pages', 1),
            "total_results": trending_data.get('total_results', len(results))
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch trending movies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trending/tv")
async def api_trending_tv(
    time_window: str = "week",
    page: int = 1,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get trending TV shows from TMDB with Plex library status and pagination."""
    from src.TMDB import get_trending, download_image
    from src.plex import check_media_exists
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Get trending data with pagination
        trending_data = get_trending('tv', time_window, page)
        results = trending_data.get('results', [])
        
        # Download and cache images for each show
        for item in results:
            if item.get('poster_path'):
                cached_path = download_image(item['poster_path'], 'w500', 'trending')
                if cached_path:
                    item['poster_url'] = f"/cache-images/{cached_path}"
            
            if item.get('backdrop_path'):
                cached_path = download_image(item['backdrop_path'], 'w500', 'trending')
                if cached_path:
                    item['backdrop_url'] = f"/cache-images/{cached_path}"
        
        # Check Plex library status for each show
        try:
            for item in results:
                title = item.get('name', item.get('title', ''))
                year = item.get('year')
                
                # Check if in Plex library
                plex_check = check_media_exists(title, year, 'tv')
                item['in_library'] = plex_check.get('exists', False)
                item['plex_title'] = plex_check.get('plex_title', '')
        except Exception as e:
            logger.warning(f"Failed to check Plex library: {e}")
            # Continue without library status
            for item in results:
                item['in_library'] = False
        
        return {
            "results": results,
            "time_window": time_window,
            "page": trending_data.get('page', page),
            "total_pages": trending_data.get('total_pages', 1),
            "total_results": trending_data.get('total_results', len(results))
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch trending TV: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
        return {"results": results, "time_window": time_window}
        
    except Exception as e:
        logger.error(f"Failed to fetch trending TV: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/search")
async def api_search(
    query: str,
    page: int = 1,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search TMDB for movies and TV shows with Plex library status."""
    from src.TMDB import get_or_fetch_search
    from src.plex import check_media_exists
    import logging
    logger = logging.getLogger(__name__)
    
    if not query or len(query.strip()) == 0:
        return {"movies": {"results": [], "page": 1, "total_pages": 0, "total_results": 0},
                "tv": {"results": [], "page": 1, "total_pages": 0, "total_results": 0}}
    
    try:
        # Get cached search results
        results = get_or_fetch_search(query, current_user.id, page, 'multi')
        
        # Check Plex library status
        try:
            # Check movies
            for item in results['movies']['results']:
                title = item.get('title', '')
                year = item.get('year')
                plex_check = check_media_exists(title, year, 'movie')
                item['in_library'] = plex_check.get('exists', False)
                item['plex_title'] = plex_check.get('plex_title', '')
            
            # Check TV shows
            for item in results['tv']['results']:
                title = item.get('name', item.get('title', ''))
                year = item.get('year')
                plex_check = check_media_exists(title, year, 'tv')
                item['in_library'] = plex_check.get('exists', False)
                item['plex_title'] = plex_check.get('plex_title', '')
                    
        except Exception as e:
            logger.warning(f"Failed to check Plex library: {e}")
            # Continue without library status
            for item in results['movies']['results'] + results['tv']['results']:
                item['in_library'] = False
        
        return results
        
    except Exception as e:
        logger.error(f"Search failed for query '{query}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/requests/{request_id}/status")
async def api_request_status(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get status of a media request for polling."""
    from src.models import MediaRequest, Download
    from src.qbittorrent import get_qbittorrent_client
    
    # Find request
    media_request = db.query(MediaRequest).filter(MediaRequest.id == request_id).first()
    
    if not media_request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Check ownership (users can only poll their own requests unless admin)
    if media_request.user_id != current_user.id and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Calculate progress based on downloads
    downloads = db.query(Download).filter(Download.media_request_id == request_id).all()
    
    total_progress = 0
    total_speed = 0
    total_eta = 0
    active_downloads = 0
    
    if downloads:
        total_progress = sum(d.progress for d in downloads) / len(downloads)
        
        # Get download speed and ETA from qBittorrent for active downloads
        if media_request.status == 'downloading':
            try:
                qb = get_qbittorrent_client()
                for download in downloads:
                    if download.status == 'downloading' and download.torrent_hash:
                        try:
                            torrent_info = qb.torrents_info(torrent_hashes=download.torrent_hash)
                            if torrent_info and len(torrent_info) > 0:
                                torrent = torrent_info[0]
                                total_speed += torrent.get('dlspeed', 0)
                                eta = torrent.get('eta', 0)
                                if eta > 0 and eta < 8640000:  # Ignore if > 100 days
                                    total_eta += eta
                                    active_downloads += 1
                        except Exception as e:
                            print(f"Error fetching torrent info for {download.torrent_hash}: {e}")
                            continue
            except Exception as e:
                print(f"Error connecting to qBittorrent: {e}")
    
    # Calculate average ETA if we have active downloads
    avg_eta = (total_eta / active_downloads) if active_downloads > 0 else 0
    
    response = {
        "request_id": request_id,
        "status": media_request.status,
        "progress": round(total_progress, 2),
        "title": media_request.title,
        "media_type": media_request.media_type
    }
    
    # Add speed and ETA if downloading
    if total_speed > 0:
        response["download_speed"] = total_speed  # bytes per second
    if avg_eta > 0:
        response["eta"] = int(avg_eta)  # seconds
    
    # Log the response for debugging
    print(f"[STATUS API] Request {request_id} | Status: {media_request.status} | Progress: {round(total_progress, 2)}% | Downloads: {len(downloads)}")
    
    return response


@app.get("/media/{media_type}/{tmdb_id}", response_class=HTMLResponse)
async def media_details_page(
    request: Request,
    media_type: str,
    tmdb_id: int,
    db: Session = Depends(get_db)
):
    """Serve media details page."""
    try:
        # Get current user using standard authentication
        user = await get_current_user(request, db)
        
        # Fetch TMDB metadata
        from src.TMDB import get_movie_details, get_tv_details
        
        if media_type == 'movie':
            media_data = get_movie_details(tmdb_id)
        elif media_type == 'tv':
            media_data = get_tv_details(tmdb_id)
        else:
            raise HTTPException(status_code=400, detail="Invalid media type")
        
        if not media_data:
            raise HTTPException(status_code=404, detail="Media not found")
        
        # Check Plex library
        from src.plex import check_media_exists
        try:
            title = media_data.get('title') or media_data.get('name', '')
            year = media_data.get('year')
            plex_check = check_media_exists(title, year, media_type)
            media_data['in_library'] = plex_check.get('exists', False)
            media_data['plex_title'] = plex_check.get('plex_title', '')
        except Exception as e:
            print(f"Error checking Plex: {e}")
            media_data['in_library'] = False
        
        # Render template
        return templates.TemplateResponse(
            "media_details.html",
            {
                "request": request,
                "user": user,
                "media": media_data,
                "media_type": media_type,
                "tmdb_id": tmdb_id,
                "current_page": "home"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Media details page failed: {e}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(url="/home", status_code=302)


@app.get("/api/media/{tmdb_id}/status")
async def get_media_status(
    tmdb_id: int,
    media_type: str = "movie",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get the current status of a media item.
    Returns state (unrequested/pending/downloading/processing/verifying/available) and progress.
    """
    from src.models import MediaRequest, Download
    from src.plex import check_media_exists
    from src.TMDB import get_movie_details, get_tv_details
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Get media title from TMDB
        if media_type == 'movie':
            media_data = get_movie_details(tmdb_id)
        else:
            media_data = get_tv_details(tmdb_id)
        
        if not media_data:
            raise HTTPException(status_code=404, detail="Media not found")
        
        title = media_data.get('title') or media_data.get('name', '')
        year = media_data.get('year')
        
        # Check if in Plex library
        plex_check = check_media_exists(title, year, media_type)
        if plex_check.get('exists', False):
            return {
                "state": "available",
                "progress": 100,
                "title": title,
                "in_library": True
            }
        
        # Check if there's a media request
        media_request = db.query(MediaRequest).filter(
            MediaRequest.tmdb_id == tmdb_id,
            MediaRequest.media_type == media_type
        ).order_by(MediaRequest.requested_at.desc()).first()
        
        if not media_request:
            return {
                "state": "unrequested",
                "progress": 0,
                "title": title,
                "in_library": False
            }
        
        # Map MediaRequest status to display state
        status_map = {
            "pending": "pending",
            "downloading": "downloading",
            "processing": "verifying",  # Files being copied/verified
            "available": "available",
            "failed": "failed"
        }
        
        state = status_map.get(media_request.status, media_request.status)
        
        # Calculate progress from downloads
        progress = 0
        if media_request.status == "downloading":
            downloads = db.query(Download).filter(
                Download.media_request_id == media_request.id
            ).all()
            
            if downloads:
                total_progress = sum(d.progress for d in downloads)
                progress = round(total_progress / len(downloads), 2)
        elif media_request.status == "processing":
            progress = 95  # Show near-complete for processing
        elif media_request.status == "available":
            progress = 100
        
        return {
            "state": state,
            "progress": progress,
            "title": title,
            "in_library": media_request.status == "available",
            "status": media_request.status,
            "request_id": media_request.id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get media status: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/media/{tmdb_id}/request-id")
async def get_media_request_id(
    tmdb_id: int,
    media_type: str = "movie",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get the request ID for a media item if one exists.
    Used to resume polling after page refresh.
    """
    from src.models import MediaRequest
    
    # Find the most recent request for this media
    media_request = db.query(MediaRequest).filter(
        MediaRequest.tmdb_id == tmdb_id,
        MediaRequest.media_type == media_type,
        MediaRequest.status.in_(['pending', 'downloading', 'processing'])
    ).order_by(MediaRequest.requested_at.desc()).first()
    
    if not media_request:
        return {"request_id": None}
    
    return {"request_id": media_request.id}


@app.get("/api/media/{tmdb_id}/season/{season_number}/episodes")
async def get_season_episodes(
    tmdb_id: int,
    season_number: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get episode details for a specific season with TMDB still images.
    Returns episode list with numbers, names, overviews, air dates, and still paths.
    """
    from src.TMDB import safe_tmdb_call, season_service, download_image
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Get season details directly from TMDB (includes all episode data)
        logger.info(f"Fetching season {season_number} details for TMDB ID {tmdb_id}")
        # Use Season service with details method
        season_details = safe_tmdb_call(season_service.details, tmdb_id, season_number)
        
        if not season_details or not hasattr(season_details, 'episodes'):
            return {
                "season_number": season_number,
                "episodes": []
            }
        
        # Extract episode information and download still images
        episodes = []
        for ep in season_details.episodes:
            still_path = ep.still_path if hasattr(ep, 'still_path') else None
            
            # Download still image to cache before returning
            if still_path:
                download_image(still_path, size='w185', cache_type='trending')
            
            episode_info = {
                "episode_number": ep.episode_number if hasattr(ep, 'episode_number') else 0,
                "name": ep.name if hasattr(ep, 'name') else f'Episode {ep.episode_number if hasattr(ep, "episode_number") else 0}',
                "overview": ep.overview if hasattr(ep, 'overview') else 'No description available.',
                "air_date": ep.air_date if hasattr(ep, 'air_date') else None,
                "still_path": still_path,
                "vote_average": ep.vote_average if hasattr(ep, 'vote_average') else 0
            }
            episodes.append(episode_info)
        
        return {
            "season_number": season_number,
            "episode_count": len(episodes),
            "episodes": episodes
        }
        
    except Exception as e:
        logger.error(f"Failed to get season episodes: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Dashboard & System Pages
# ============================================================================

@app.get("/dashboard", response_class=HTMLResponse)
async def system_dashboard(
    request: Request,
    user: User = Depends(get_current_user)
):
    """
    System dashboard showing disk usage, transfer stats, and service health.
    """
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "current_page": "dashboard"
    })


@app.get("/downloads-view", response_class=HTMLResponse)
async def downloads_view(
    request: Request,
    user: User = Depends(get_current_user)
):
    """
    Active downloads page showing all torrents with filtering and sorting.
    """
    return templates.TemplateResponse("active_downloads.html", {
        "request": request,
        "user": user,
        "current_page": "downloads"
    })


@app.get("/calendar", response_class=HTMLResponse)
async def calendar_view(
    request: Request,
    user: User = Depends(get_current_user)
):
    """
    Calendar page showing upcoming TV episode releases for tracked shows.
    """
    return templates.TemplateResponse("calendar.html", {
        "request": request,
        "user": user,
        "current_page": "calendar"
    })


@app.get("/api/calendar/episodes")
async def api_calendar_episodes(
    year: int,
    month: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get upcoming TV episode releases for calendar view.
    Loads 3 months (requested month ±1) for smooth navigation.
    Returns episodes with air dates and request status.
    
    Args:
        year: Year (e.g., 2026)
        month: Month (1-12)
        
    Returns:
        JSON with episodes grouped by air date
    """
    from src.models import TMDBSeasonCache, SeasonRequest
    from src.TMDB import season_service, safe_tmdb_call
    from datetime import date
    from calendar import monthrange
    
    try:
        # Calculate 3-month range (requested ±1 month)
        # Start: First day of previous month
        if month == 1:
            start_year, start_month = year - 1, 12
        else:
            start_year, start_month = year, month - 1
        start_date = date(start_year, start_month, 1)
        
        # End: Last day of next month
        if month == 12:
            end_year, end_month = year + 1, 1
        else:
            end_year, end_month = year, month + 1
        _, last_day = monthrange(end_year, end_month)
        end_date = date(end_year, end_month, last_day)
        
        logger.info(f"[CALENDAR API] User {current_user.username} - Fetching episodes from {start_date} to {end_date}")
        
        # Get all tracked TV shows for this user
        tracked_requests = db.query(MediaRequest).filter(
            MediaRequest.user_id == current_user.id,
            MediaRequest.media_type == 'tv',
            MediaRequest.track_upcoming == 1,
            MediaRequest.status != 'deleted'
        ).all()
        
        if not tracked_requests:
            return {
                "episodes": [],
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "requested_month": f"{year}-{month:02d}"
            }
        
        logger.info(f"[CALENDAR API] Found {len(tracked_requests)} tracked shows")
        
        calendar_episodes = []
        
        for media_request in tracked_requests:
            try:
                # Get all ongoing seasons for this show
                ongoing_seasons = db.query(TMDBSeasonCache).filter(
                    TMDBSeasonCache.tmdb_id == media_request.tmdb_id,
                    TMDBSeasonCache.season_status == 'ongoing'
                ).all()
                
                if not ongoing_seasons:
                    continue
                
                for season_cache in ongoing_seasons:
                    # Fetch episode details from TMDB
                    season_details = safe_tmdb_call(
                        season_service.details,
                        media_request.tmdb_id,
                        season_cache.season_number
                    )
                    
                    if not season_details or not hasattr(season_details, 'episodes'):
                        continue
                    
                    # Filter episodes by date range
                    for episode in season_details.episodes:
                        if not hasattr(episode, 'air_date') or not episode.air_date:
                            continue
                        
                        try:
                            ep_air_date = datetime.strptime(episode.air_date, '%Y-%m-%d').date()
                        except:
                            continue
                        
                        # Only include episodes in 3-month range
                        if not (start_date <= ep_air_date <= end_date):
                            continue
                        
                        episode_num = episode.episode_number
                        
                        # Check if episode is requested (look for SeasonRequest)
                        season_request = db.query(SeasonRequest).join(Download).filter(
                            Download.media_request_id == media_request.id,
                            SeasonRequest.season_number == season_cache.season_number,
                            SeasonRequest.episode_numbers.like(f'%{episode_num}%')
                        ).first()
                        
                        # Get download status if exists
                        download_status = None
                        download_progress = None
                        if season_request:
                            download = db.query(Download).filter(
                                Download.id == season_request.download_id
                            ).first()
                            if download:
                                download_status = download.status
                                download_progress = download.progress
                        
                        calendar_episodes.append({
                            "id": f"{media_request.tmdb_id}_s{season_cache.season_number}_e{episode_num}",
                            "tmdb_id": media_request.tmdb_id,
                            "show_title": media_request.title,
                            "season": season_cache.season_number,
                            "episode": episode_num,
                            "episode_title": episode.name if hasattr(episode, 'name') else '',
                            "air_date": episode.air_date,
                            "overview": episode.overview if hasattr(episode, 'overview') else '',
                            "still_path": episode.still_path if hasattr(episode, 'still_path') else None,
                            "is_requested": season_request is not None,
                            "download_status": download_status,
                            "download_progress": download_progress,
                            "media_request_id": media_request.id
                        })
            
            except Exception as e:
                logger.error(f"[CALENDAR API] Error processing {media_request.title}: {e}")
                continue
        
        # Sort by air date
        calendar_episodes.sort(key=lambda x: x['air_date'])
        
        logger.info(f"[CALENDAR API] Returning {len(calendar_episodes)} episodes")
        
        return {
            "episodes": calendar_episodes,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "requested_month": f"{year}-{month:02d}"
        }
        
    except Exception as e:
        logger.error(f"[CALENDAR API] Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/external/plex")
async def redirect_plex(user: User = Depends(get_current_user)):
    """
    Redirect to Plex web interface.
    """
    plex_url = os.getenv('PLEX_URL', 'http://localhost:32400')
    return RedirectResponse(url=f"{plex_url}/web", status_code=302)


@app.get("/external/prowlarr")
async def redirect_prowlarr(user: User = Depends(get_current_user)):
    """
    Redirect to Prowlarr web interface.
    """
    prowlarr_url = os.getenv('PROWLARR_URL', 'http://localhost:9696')
    return RedirectResponse(url=prowlarr_url, status_code=302)


@app.get("/external/qbittorrent")
async def redirect_qbittorrent(user: User = Depends(get_current_user)):
    """
    Redirect to qBittorrent web interface.
    """
    qbit_url = os.getenv('QBITTORRENT_URL', 'http://localhost:8080')
    return RedirectResponse(url=qbit_url, status_code=302)


# ============================================================================
# Dashboard API Endpoints
# ============================================================================

@app.get("/api/system/disk-usage")
async def get_disk_usage(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get disk usage information for downloads, TV, and movies directories.
    Handles deduplication if directories are on the same partition.
    """
    try:
        import psutil
        
        paths = {
            'downloads': os.getenv('DOWNLOADS_PATH'),
            'tv': os.getenv('TV_PATH'),
            'movies': os.getenv('MOVIES_PATH')
        }
        
        # Track unique partitions to avoid duplication
        partitions_seen = {}
        disk_info = []
        
        for name, path in paths.items():
            if not path or not os.path.exists(path):
                logger.warning(f"Path '{name}' not found: {path}")
                continue
            
            try:
                # Get disk usage for this path
                usage = psutil.disk_usage(path)
                
                # Get the partition/mount point
                # On Windows, this returns the drive letter
                # On Unix, this returns the mount point
                if os.name == 'nt':
                    # Windows: get drive letter (e.g., 'C:')
                    partition = os.path.splitdrive(path)[0]
                    if not partition:
                        partition = path
                else:
                    # Unix: get mount point
                    partition = os.path.realpath(path)
                
                # Check if we've already seen this partition
                if partition in partitions_seen:
                    # Add path to existing partition entry
                    partitions_seen[partition]['paths'].append(name)
                else:
                    # New partition
                    partition_info = {
                        'partition': partition,
                        'paths': [name],
                        'total_bytes': usage.total,
                        'used_bytes': usage.used,
                        'free_bytes': usage.free,
                        'percent_used': usage.percent,
                        'total_gb': round(usage.total / (1024**3), 2),
                        'used_gb': round(usage.used / (1024**3), 2),
                        'free_gb': round(usage.free / (1024**3), 2),
                        'warning_level': 'critical' if usage.percent > 90 else 'warning' if usage.percent > 80 else 'normal'
                    }
                    partitions_seen[partition] = partition_info
                    disk_info.append(partition_info)
            except Exception as path_error:
                logger.error(f"Error getting disk usage for {name} ({path}): {path_error}")
                continue
        
        return {
            "disk_usage": disk_info,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get disk usage: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system/transfer-stats")
async def get_transfer_stats(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get global transfer statistics from qBittorrent.
    """
    try:
        # Get global transfer info
        # Note: This requires qBittorrent API endpoint /api/v2/transfer/info
        # We'll use requests directly since it may not be in the client wrapper
        import requests
        
        qbit_url = os.getenv('QBITTORRENT_URL')
        username = os.getenv('QBITTORRENT_USERNAME')
        password = os.getenv('QBITTORRENT_PASSWORD')
        
        if not qbit_url or not username or not password:
            raise HTTPException(status_code=500, detail="qBittorrent configuration missing")
        
        # Login to qBittorrent
        session = requests.Session()
        login_resp = session.post(f"{qbit_url}/api/v2/auth/login", data={
            'username': username,
            'password': password
        }, timeout=5)
        
        if login_resp.text != 'Ok.':
            raise HTTPException(status_code=500, detail="qBittorrent authentication failed")
        
        # Get transfer info
        response = session.get(f"{qbit_url}/api/v2/transfer/info", timeout=5)
        response.raise_for_status()
        transfer_info = response.json()
        
        # Get torrent counts by status
        torrents_response = session.get(f"{qbit_url}/api/v2/torrents/info", timeout=5)
        torrents = torrents_response.json() if torrents_response.ok else []
        
        # Count by status
        status_counts = {
            'downloading': 0,
            'seeding': 0,
            'paused': 0,
            'error': 0,
            'total': len(torrents)
        }
        
        for torrent in torrents:
            state = torrent.get('state', '').lower()
            if 'downloading' in state or 'downloading' in state:
                status_counts['downloading'] += 1
            elif 'seeding' in state or 'uploading' in state:
                status_counts['seeding'] += 1
            elif 'paused' in state:
                status_counts['paused'] += 1
            elif 'error' in state or 'missing' in state:
                status_counts['error'] += 1
        
        return {
            "dl_speed": transfer_info.get('dl_info_speed', 0),  # bytes/s
            "up_speed": transfer_info.get('up_info_speed', 0),  # bytes/s
            "dl_total": transfer_info.get('dl_info_data', 0),   # bytes
            "up_total": transfer_info.get('up_info_data', 0),   # bytes
            "dl_speed_mbps": round(transfer_info.get('dl_info_speed', 0) / (1024**2), 2),
            "up_speed_mbps": round(transfer_info.get('up_info_speed', 0) / (1024**2), 2),
            "dl_total_gb": round(transfer_info.get('dl_info_data', 0) / (1024**3), 2),
            "up_total_gb": round(transfer_info.get('up_info_data', 0) / (1024**3), 2),
            "status_counts": status_counts,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get transfer stats: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system/health-check")
async def system_health_check(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Check connectivity to Plex, Prowlarr, and qBittorrent services.
    """
    services = {}
    
    # Check Plex
    try:
        from src.plex import get_plex_server
        plex = get_plex_server()
        services['plex'] = {
            'status': 'online',
            'url': os.getenv('PLEX_URL'),
            'version': plex.version if hasattr(plex, 'version') else 'unknown'
        }
    except Exception as e:
        services['plex'] = {
            'status': 'offline',
            'url': os.getenv('PLEX_URL'),
            'error': str(e)
        }
    
    # Check Prowlarr
    try:
        import requests
        prowlarr_url = os.getenv('PROWLARR_URL')
        prowlarr_key = os.getenv('PROWLARR_API_KEY')
        response = requests.get(
            f"{prowlarr_url}/api/v1/system/status",
            headers={'X-Api-Key': prowlarr_key},
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        services['prowlarr'] = {
            'status': 'online',
            'url': prowlarr_url,
            'version': data.get('version', 'unknown')
        }
    except Exception as e:
        services['prowlarr'] = {
            'status': 'offline',
            'url': os.getenv('PROWLARR_URL'),
            'error': str(e)
        }
    
    # Check qBittorrent
    try:
        import requests
        qbit_url = os.getenv('QBITTORRENT_URL')
        username = os.getenv('QBITTORRENT_USERNAME')
        password = os.getenv('QBITTORRENT_PASSWORD')
        
        session = requests.Session()
        login_response = session.post(f"{qbit_url}/api/v2/auth/login", data={
            'username': username,
            'password': password
        }, timeout=5)
        
        if login_response.text == 'Ok.':
            version_response = session.get(f"{qbit_url}/api/v2/app/version", timeout=5)
            services['qbittorrent'] = {
                'status': 'online',
                'url': qbit_url,
                'version': version_response.text.strip('v"') if version_response.ok else 'unknown'
            }
        else:
            services['qbittorrent'] = {
                'status': 'offline',
                'url': qbit_url,
                'error': 'Authentication failed'
            }
    except Exception as e:
        services['qbittorrent'] = {
            'status': 'offline',
            'url': os.getenv('QBITTORRENT_URL'),
            'error': str(e)
        }
    
    return {
        "services": services,
        "timestamp": datetime.datetime.now().isoformat()
    }


# NOTE: /api/downloads/active and /api/downloads/test have been moved to downloads.py router
# They are now at /api/downloads/active and /api/downloads/test via the downloads_router
# This was necessary to fix route conflict with /api/downloads/{download_id}
