"""
FastAPI application configuration and main entry point.
Handles routing, middleware, and application lifecycle.
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException
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
from src.models import User

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


# Dashboard route (redirects to homepage)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """
    Redirect dashboard to new homepage.
    """
    return RedirectResponse(url="/home", status_code=302)


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
            {"request": request, "user": user}
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
                "tmdb_id": tmdb_id
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
