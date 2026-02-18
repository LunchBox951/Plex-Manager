"""
Downloads API router for qBittorrent torrent management.
Provides endpoints for adding, monitoring, and managing downloads.
Includes media request workflow with Prowlarr integration.
"""

import os
import json
import time
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.models import User
from src.pickle_models import Download, SeasonRequest, MediaRequest, EpisodeRetention
from src.pickle_stores import download_store, season_request_store, media_request_store, episode_retention_store, tmdb_season_cache_store
from src.qbittorrent import get_qbittorrent_client, QBittorrentClient
from src.torrent_validator import validate_torrent_files
from src.auth import get_current_user
from src.retention import get_effective_retention
from src.utils import normalize_title
from src.console import print_info, print_warning, print_error, print_debug, print_monitor, print_success


router = APIRouter()


# ============================================================================
# Helper Functions
# ============================================================================

async def await_torrent_connection(
    qb: QBittorrentClient, 
    info_hash: str, 
    max_retries: int = 5,
    intervals: List[int] = None
) -> tuple[bool, Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Wait for torrent to connect and retrieve metadata with progressive retry intervals.
    
    Progressive retry strategy:
    - Attempt 1-3: Wait 10 seconds between attempts
    - Attempt 4: Wait 30 seconds
    - Attempt 5: Wait 60 seconds
    
    Args:
        qb: qBittorrent client instance
        info_hash: Torrent info hash
        max_retries: Maximum number of retry attempts (default: 5)
        intervals: Custom wait intervals in seconds (default: [10, 10, 10, 30, 60])
    
    Returns:
        tuple: (success, torrent_info, files)
            - success: True if connection successful
            - torrent_info: Torrent metadata dict or None
            - files: List of file dicts or None
    """
    if intervals is None:
        intervals = [10, 10, 10, 30, 60]
    
    for attempt in range(max_retries):
        try:
            # Try to get torrent info
            torrent_info = qb.get_torrent_info(info_hash)
            
            if torrent_info:
                # Successfully got info, now try to get files
                files = qb.get_torrent_files(info_hash)
                
                if files:
                    print_info(f"✓ Torrent connected on attempt {attempt + 1}/{max_retries}", prefix="DOWNLOADS")
                    return (True, torrent_info, files)
                else:
                    print_warning(f"Torrent info found but no files yet (attempt {attempt + 1}/{max_retries})", prefix="DOWNLOADS")
            else:
                print_warning(f"Torrent not found in qBittorrent (attempt {attempt + 1}/{max_retries})", prefix="DOWNLOADS")
            
            # If not last attempt, wait before retry using async sleep
            if attempt < max_retries - 1:
                wait_time = intervals[attempt] if attempt < len(intervals) else intervals[-1]
                print_info(f"Waiting {wait_time}s before retry...", prefix="DOWNLOADS")
                await asyncio.sleep(wait_time)
        
        except Exception as e:
            print_error(f"Error checking torrent on attempt {attempt + 1}: {e}", prefix="DOWNLOADS")
            if attempt < max_retries - 1:
                wait_time = intervals[attempt] if attempt < len(intervals) else intervals[-1]
                await asyncio.sleep(wait_time)
    
    print_error(f"✗ Failed to connect to torrent after {max_retries} attempts", prefix="DOWNLOADS")
    return (False, None, None)


# Request/Response models
class AddDownloadRequest(BaseModel):
    """Request model for adding a new download."""
    magnet_link: str
    media_type: str  # 'movie' or 'tv'
    target_seed_ratio: Optional[float] = 1.0
    timeout_days: Optional[int] = 15


class DownloadResponse(BaseModel):
    """Response model for download information."""
    id: int
    torrent_hash: str
    status: str
    progress: float
    seed_ratio: float
    target_seed_ratio: float
    media_type: str
    timeout_days: int
    failed_reason: Optional[str]
    added_at: str
    completed_at: Optional[str]
    failed_at: Optional[str]
    will_timeout_at: Optional[str]
    media_request_id: Optional[int] = None


@router.post("/downloads/add", response_model=DownloadResponse)
async def add_download(
    request: AddDownloadRequest
):
    """
    Add a new torrent download from magnet link.
    
    Process:
    1. Extract info_hash from magnet link
    2. Check if already exists in database
    3. Add to qBittorrent (retrieves metadata)
    4. Validate file types
    5. Create Download record
    """
    qb = get_qbittorrent_client()
    
    # Validate media type
    if request.media_type not in ['movie', 'tv']:
        raise HTTPException(status_code=400, detail="media_type must be 'movie' or 'tv'")
    
    # Extract info hash
    info_hash = QBittorrentClient.extract_info_hash(request.magnet_link)
    if not info_hash:
        raise HTTPException(status_code=400, detail="Invalid magnet link format")
    
    # Check for duplicate
    existing = download_store.find_by_index('torrent_hash', info_hash)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Download already exists with status: {existing.status}"
        )
    
    # Get downloads path from environment
    downloads_path = os.getenv('DOWNLOADS_PATH')
    if not downloads_path:
        raise HTTPException(status_code=500, detail="DOWNLOADS_PATH not configured")
    
    # Add magnet to qBittorrent
    category = request.media_type  # Use media type as category
    success = qb.add_magnet(request.magnet_link, save_path=downloads_path, category=category)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to add magnet to qBittorrent")
    
    # Wait a moment for qBittorrent to process the magnet
    import time
    time.sleep(2)
    
    # Get torrent info and files for validation
    torrent_info = qb.get_torrent_info(info_hash)
    if not torrent_info:
        raise HTTPException(status_code=500, detail="Failed to retrieve torrent info from qBittorrent")
    
    torrent_files = qb.get_torrent_files(info_hash)
    
    # Validate files
    validation_result = validate_torrent_files(torrent_files)
    if not validation_result.valid:
        # Remove from qBittorrent
        qb.delete_torrent(info_hash, delete_files=True)
        raise HTTPException(status_code=400, detail=f"Validation failed: {validation_result.reason}")
    
    # Calculate timeout date
    timeout_days = request.timeout_days if request.timeout_days is not None else 15
    will_timeout_at = datetime.utcnow() + timedelta(days=timeout_days)
    
    # Create Download record
    download = Download(
        torrent_hash=info_hash,
        magnet_link=request.magnet_link,
        status="downloading",
        progress=torrent_info.get('progress', 0) * 100,  # Convert to percentage
        seed_ratio=torrent_info.get('ratio', 0),
        target_seed_ratio=request.target_seed_ratio,
        metadata_json=json.dumps({
            "name": torrent_info.get('name'),
            "size": torrent_info.get('size'),
            "files": validation_result.valid_files
        }),
        download_path=torrent_info.get('save_path'),
        media_type=request.media_type,
        timeout_days=request.timeout_days,
        will_timeout_at=will_timeout_at
    )
    
    download = download_store.save(download)
    
    # Convert to response using to_dict
    download_dict = download.to_dict()
    return DownloadResponse(**download_dict)


@router.get("/downloads", response_model=List[DownloadResponse])
async def list_downloads(
    status: Optional[str] = None,
    media_type: Optional[str] = None
):
    """
    List all downloads with optional filtering.
    Returns database snapshot only (no real-time qBittorrent queries).
    """
    if status:
        downloads = download_store.list_by_index('status', status)
    else:
        downloads = download_store.list_all()
    
    if media_type:
        downloads = [d for d in downloads if d.media_type == media_type]
    
    # Sort by added_at desc
    downloads.sort(key=lambda d: d.added_at, reverse=True)
    
    return [DownloadResponse(**d.to_dict()) for d in downloads]


# Test endpoint to verify authentication works
@router.get("/downloads/test")
async def test_downloads_endpoint(
    test_param: str = "default",
    current_user: User = Depends(get_current_user)
):
    return {
        "status": "ok",
        "test_param": test_param,
        "user": current_user.username
    }


@router.get("/downloads/active")
async def get_active_downloads(
    status: str = "all",
    sort_by: str = "date",
    search: str = "",
    current_user: User = Depends(get_current_user)
):
    """
    Get all active downloads from qBittorrent with filtering and sorting.
    
    Args:
        status: Filter by status (downloading, seeding, paused, completed, all)
        sort_by: Sort field (name, progress, speed, date, size)
        search: Search by torrent name
    """
    try:
        import requests
        import os
        
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
        
        # Get all torrents
        params = {}
        if status and status != 'all':
            params['filter'] = status
        
        response = session.get(f"{qbit_url}/api/v2/torrents/info", params=params, timeout=5)
        response.raise_for_status()
        torrents = response.json()
        
        # Apply search filter
        if search and search.strip():
            search_lower = search.lower()
            torrents = [t for t in torrents if search_lower in t.get('name', '').lower()]
        
        # Get request counts
        request_counts = {
            'pending': len(media_request_store.list_by_index('status', 'pending')),
            'downloading': len(media_request_store.list_by_index('status', 'downloading')),
            'processing': len(media_request_store.list_by_index('status', 'processing')),
            'total': len(media_request_store.list_all())
        }
        
        # Format torrent data
        formatted_torrents = []
        for torrent in torrents:
            formatted_torrents.append({
                'hash': torrent.get('hash'),
                'name': torrent.get('name'),
                'state': torrent.get('state'),
                'progress': round(torrent.get('progress', 0) * 100, 2),
                'size': torrent.get('size', 0),
                'size_gb': round(torrent.get('size', 0) / (1024**3), 2),
                'downloaded': torrent.get('downloaded', 0),
                'downloaded_gb': round(torrent.get('downloaded', 0) / (1024**3), 2),
                'dl_speed': torrent.get('dlspeed', 0),
                'dl_speed_mbps': round(torrent.get('dlspeed', 0) / (1024**2), 2),
                'up_speed': torrent.get('upspeed', 0),
                'up_speed_mbps': round(torrent.get('upspeed', 0) / (1024**2), 2),
                'eta': torrent.get('eta', 0),
                'eta_formatted': format_eta(torrent.get('eta', 0)),
                'ratio': round(torrent.get('ratio', 0), 2),
                'num_seeds': torrent.get('num_seeds', 0),
                'num_leechs': torrent.get('num_leechs', 0),
                'added_on': torrent.get('added_on', 0),
                'completion_on': torrent.get('completion_on', 0),
                'category': torrent.get('category', ''),
                'save_path': torrent.get('save_path', '')
            })
        
        # Sort torrents
        if sort_by == 'name':
            formatted_torrents.sort(key=lambda x: x['name'].lower())
        elif sort_by == 'progress':
            formatted_torrents.sort(key=lambda x: x['progress'], reverse=True)
        elif sort_by == 'speed':
            formatted_torrents.sort(key=lambda x: x['dl_speed'], reverse=True)
        elif sort_by == 'size':
            formatted_torrents.sort(key=lambda x: x['size'], reverse=True)
        elif sort_by == 'date':
            formatted_torrents.sort(key=lambda x: x['added_on'], reverse=True)
        
        return {
            "torrents": formatted_torrents,
            "request_counts": request_counts,
            "total_count": len(formatted_torrents),
            "filters": {
                "status": status or "all",
                "sort_by": sort_by,
                "search": search or ""
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print_error(f"Failed to get active downloads: {e}", prefix="DOWNLOADS")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def format_eta(seconds):
    """Format ETA seconds into human-readable string."""
    if seconds < 0 or seconds == 8640000:  # qBittorrent uses 8640000 for infinite
        return "∞"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    if hours > 24:
        days = hours // 24
        return f"{days}d {hours % 24}h"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


@router.get("/downloads/{download_id}", response_model=DownloadResponse)
async def get_download(
    download_id: int
):
    """Get detailed information about a specific download."""
    download = download_store.load(download_id)
    
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    
    return DownloadResponse(**download.to_dict())


@router.delete("/downloads/{download_id}")
async def delete_download(
    download_id: int,
    delete_files: bool = False
):
    """
    Delete a download and optionally remove from qBittorrent.
    
    Args:
        download_id: Download ID
        delete_files: Whether to also delete files from disk
    """
    download = download_store.load(download_id)
    
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    
    qb = get_qbittorrent_client()
    
    # Remove from qBittorrent if still active
    if download.status in ['downloading', 'seeding', 'pending']:
        qb.delete_torrent(str(download.torrent_hash), delete_files=delete_files)
    
    # Delete from store
    download_store.delete(download_id)
    
    return {"message": "Download deleted successfully"}


@router.get("/downloads/failed-hashes", response_model=List[str])
async def get_failed_hashes():
    """
    Get list of info hashes for failed downloads.
    Used by requesting system to exclude problematic magnets.
    """
    failed_ids = download_store.get_ids_by_index_multi('status', ['failed', 'partial_failed'])
    failed_downloads = [download_store.load(id) for id in failed_ids if download_store.load(id)]
    
    return [d.torrent_hash for d in failed_downloads]


@router.post("/downloads/{download_id}/pause")
async def pause_download(
    download_id: int
):
    """Pause a download in qBittorrent."""
    download = download_store.load(download_id)
    
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    
    if download.status not in ['downloading', 'seeding']:
        raise HTTPException(status_code=400, detail="Download cannot be paused in current state")
    
    qb = get_qbittorrent_client()
    success = qb.pause_torrent(str(download.torrent_hash))
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to pause torrent")
    
    return {"message": "Download paused successfully"}


@router.post("/downloads/{download_id}/resume")
async def resume_download(
    download_id: int
):
    """Resume a paused download in qBittorrent."""
    download = download_store.load(download_id)
    
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    
    qb = get_qbittorrent_client()
    success = qb.resume_torrent(str(download.torrent_hash))
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to resume torrent")
    
    return {"message": "Download resumed successfully"}


# ============================================================================
# Media Request Workflow with Prowlarr
# ============================================================================

class MediaRequestModel(BaseModel):
    """Request model for media download request."""
    tmdb_id: int
    media_type: str  # 'movie' or 'tv'
    season: Optional[int] = None  # Required for TV
    episodes: Optional[List[int]] = None  # Optional - None means full season


class TorrentSearchResult(BaseModel):
    """Search result model for torrent preview."""
    title: str
    size_gb: float
    seeders: int
    leechers: int
    score: float
    indexer: str
    is_season_pack: bool
    episode_count: Optional[int] = None
    resolution: Optional[str] = None


class MediaRequestResponse(BaseModel):
    """Response model for media request."""
    status: str  # success, already_exists, partial, not_found, error
    message: str
    download_id: Optional[int] = None
    torrent: Optional[dict] = None
    plex_info: Optional[dict] = None


@router.post("/media/request", response_model=MediaRequestResponse)
async def request_media(
    request: MediaRequestModel
):
    """
    Request media download with automatic Prowlarr search and Plex verification.
    
    Workflow:
    1. Check if media already exists in Plex
    2. Get TMDB metadata (title, year)
    3. Search Prowlarr for torrents
    4. Score and rank torrents
    5. Select best torrent
    6. Add to qBittorrent
    7. Return download info
    
    Args:
        request: Media request with TMDB ID, media type, season, episodes
        db: Database session
        
    Returns:
        MediaRequestResponse with status and download info
    """
    from src.plex import check_media_exists
    from src.TMDB import get_movie_details, get_tv_details, get_season_episode_count
    from src.prowlarr import get_prowlarr_client, CATEGORY_MOVIES, CATEGORY_TV
    from src.scoring import rank_torrents, select_best_torrent
    
    print_info(f"Media request: TMDB {request.tmdb_id} ({request.media_type})", prefix="DOWNLOADS")
    
    try:
        # Step 1: Get TMDB metadata
        print_info("Fetching TMDB metadata...", prefix="DOWNLOADS")
        if request.media_type == 'movie':
            tmdb_data = get_movie_details(request.tmdb_id)
            title = tmdb_data.get('title')
            year = tmdb_data.get('year')
        else:
            tmdb_data = get_tv_details(request.tmdb_id)
            title = tmdb_data.get('name')
            year = tmdb_data.get('year')
        
        if not title:
            raise HTTPException(status_code=404, detail="Media not found on TMDB")
        
        print_info(f"Found: {title} ({year})", prefix="DOWNLOADS")
        
        # Step 2: Check Plex for existing media
        print_info("Checking Plex for duplicates...", prefix="DOWNLOADS")
        plex_check = check_media_exists(
            tmdb_title=title,
            year=year,
            media_type=request.media_type,
            season=request.season,
            episodes=request.episodes
        )
        
        if plex_check.get('exists'):
            # Handle partial TV show matches
            if plex_check.get('partial') and plex_check.get('missing_episodes'):
                # Update request to only download missing episodes
                missing_eps = plex_check['missing_episodes']
                print_info(f"Partial match in Plex, requesting missing episodes: {missing_eps}", prefix="DOWNLOADS")
                request.episodes = missing_eps
            else:
                # Media fully exists
                print_info("Media already exists in Plex", prefix="DOWNLOADS")
                return MediaRequestResponse(
                    status="already_exists",
                    message=f"{title} already available in Plex",
                    plex_info=plex_check
                )
        
        # Step 3: Search Prowlarr
        print_info("Searching Prowlarr...", prefix="DOWNLOADS")
        prowlarr = get_prowlarr_client()
        
        # Build search query
        if request.media_type == 'movie':
            query = f"{normalize_title(title)} {year}"
            category = CATEGORY_MOVIES
        else:
            normalized_title = normalize_title(title)
            query = f"{normalized_title} S{request.season:02d}" if request.season else normalized_title
            category = CATEGORY_TV
        
        torrents = prowlarr.search(query, category)
        
        if not torrents:
            raise HTTPException(status_code=422, detail=f"No torrents found for {title}")
        
        print_monitor({"torrents_found": len(torrents), "media_type": request.media_type, "title": title}, prefix="DOWNLOADS")
        
        # Step 4: Get failed hashes to exclude
        failed_ids = download_store.get_ids_by_index_multi('status', ['failed', 'partial_failed'])
        failed_downloads = [download_store.load(id) for id in failed_ids if download_store.load(id)]
        failed_hashes = {d.torrent_hash.lower() for d in failed_downloads}
        
        # Step 5: Score and rank torrents
        print_info("Scoring torrents...", prefix="DOWNLOADS")
        qb = get_qbittorrent_client()
        
        # Get original language for dual audio scoring
        original_language = tmdb_data.get('original_language')
        
        scored_torrents = rank_torrents(
            torrents=torrents,
            failed_hashes=failed_hashes,
            tmdb_id=request.tmdb_id if request.media_type == 'tv' else None,
            season_number=request.season,
            requested_episodes=request.episodes,
            qb_client=qb,
            original_language=original_language
        )
        
        if not scored_torrents:
            raise HTTPException(status_code=422, detail="No suitable torrents found after filtering")
        
        # Step 6: Select best torrent with fallback retry
        best_torrent = select_best_torrent(scored_torrents)
        
        if not best_torrent:
            raise HTTPException(status_code=422, detail="No torrents meet minimum quality requirements")
        
        print_info(f"Selected: {best_torrent.torrent.title} (score: {best_torrent.final_score:.2f})", prefix="DOWNLOADS")
        
        # Step 7: Add to qBittorrent
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Extract info hash
                info_hash = QBittorrentClient.extract_info_hash(best_torrent.torrent.magnet_link)
                if not info_hash:
                    raise ValueError("Could not extract info hash from magnet")
                
                # Check for duplicates
                existing = download_store.find_by_index('torrent_hash', info_hash)
                if existing:
                    print_info(f"Torrent already in downloads: {existing.id}", prefix="DOWNLOADS")
                    return MediaRequestResponse(
                        status="success",
                        message="Torrent already downloading",
                        download_id=existing.id,
                        torrent={
                            "title": best_torrent.torrent.title,
                            "size_gb": best_torrent.torrent.size_gb,
                            "seeders": best_torrent.torrent.seeders,
                            "score": best_torrent.final_score,
                            "indexer": best_torrent.torrent.indexer
                        }
                    )
                
                # Add to qBittorrent
                category = request.media_type
                save_path = os.getenv('DOWNLOADS_PATH', 'C:\\downloads')
                
                success = qb.add_magnet(
                    magnet_uri=best_torrent.torrent.magnet_link,
                    category=category,
                    save_path=save_path
                )
                
                if not success:
                    raise ValueError("qBittorrent failed to add magnet")
                
                # Wait for metadata
                import time
                time.sleep(2)
                
                # Get torrent info
                torrent_info = qb.get_torrent_info(info_hash)
                if not torrent_info:
                    raise ValueError("Failed to retrieve torrent info")
                
                files = qb.get_torrent_files(info_hash)
                if not files:
                    raise ValueError("No files found in torrent")
                
                # Validate files
                validation = validate_torrent_files(files)
                if not validation.valid:
                    qb.delete_torrent(info_hash, delete_files=True)
                    raise ValueError(f"Torrent validation failed: {validation.reason}")
                
                # Calculate timeout date
                timeout_date = datetime.utcnow() + timedelta(days=15)
                
                # Create download record
                download = Download(
                    torrent_hash=info_hash,
                    magnet_link=best_torrent.torrent.magnet_link,
                    status='downloading',
                    media_type=request.media_type,
                    metadata_json=json.dumps({
                        'name': torrent_info.get('name'),
                        'size': torrent_info.get('size'),
                        'num_files': len(files),
                        'indexer': best_torrent.torrent.indexer,
                        'score': best_torrent.final_score
                    }),
                    will_timeout_at=timeout_date,
                    tmdb_id=request.tmdb_id,
                    year=year,
                    season=request.season,
                    episodes=json.dumps(request.episodes) if request.episodes else None
                )
                
                download = download_store.save(download)
                
                print_monitor({"download_id": download.id, "status": "added", "media_type": request.media_type}, prefix="DOWNLOADS")
                
                # Create SeasonRequest if TV show
                if request.media_type == 'tv' and request.season:
                    season_req = SeasonRequest(
                        download_id=download.id,
                        season_number=request.season,
                        episode_numbers=json.dumps(request.episodes) if request.episodes else None,
                        status='pending'
                    )
                    season_req = season_request_store.save(season_req)
                
                return MediaRequestResponse(
                    status="success",
                    message="Torrent added to downloads",
                    download_id=download.id,
                    torrent={
                        "title": best_torrent.torrent.title,
                        "size_gb": best_torrent.torrent.size_gb,
                        "seeders": best_torrent.torrent.seeders,
                        "score": best_torrent.final_score,
                        "indexer": best_torrent.torrent.indexer,
                        "resolution": best_torrent.resolution,
                        "episode_count": best_torrent.episode_count
                    }
                )
            
            except Exception as e:
                print_error(f"Attempt {attempt + 1} failed: {e}", prefix="DOWNLOADS")
                
                if attempt < max_attempts - 1:
                    # Try next best torrent
                    if attempt + 1 < len(scored_torrents):
                        best_torrent = scored_torrents[attempt + 1]
                        print_info(f"Retrying with next torrent: {best_torrent.torrent.title}", prefix="DOWNLOADS")
                    else:
                        raise HTTPException(status_code=500, detail=f"All torrents failed: {str(e)}")
                else:
                    raise HTTPException(status_code=500, detail=f"Failed to add download: {str(e)}")
    
    except HTTPException:
        raise
    except Exception as e:
        print_error(f"Media request failed: {e}", prefix="DOWNLOADS")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Unified Media Request System
# ============================================================================

class UnifiedMediaRequestModel(BaseModel):
    """Unified request model supporting all request types."""
    tmdb_id: int
    media_type: str  # 'movie' or 'tv'
    
    # TV-specific fields
    seasons: Optional[List[int]] = None  # None = entire show, [1,2] = specific seasons
    episodes: Optional[dict] = None  # {season: [episodes]}, None = full seasons
    
    # Retention policy
    retention_type: str = "watch_once"  # forever, watch_once, watch_as_released
    episode_retention_overrides: Optional[List[dict]] = None  # [{season, episode, retention_type}]


class UnifiedMediaRequestResponse(BaseModel):
    """Comprehensive response for unified requests."""
    status: str  # success, already_exists, partial, not_found, error
    message: str
    media_request_id: Optional[int] = None
    download_ids: Optional[List[int]] = None
    torrents: Optional[List[dict]] = None
    plex_info: Optional[dict] = None
    missing_content: Optional[dict] = None  # For partial matches


@router.post("/media/request-unified", response_model=UnifiedMediaRequestResponse)
async def request_media_unified(
    request: UnifiedMediaRequestModel,
    current_user: User = Depends(get_current_user)
):
    """
    Unified media request endpoint handling the complete workflow.
    
    Supports:
    - Movies: Simple request with retention policy
    - TV Episodes: Single or multiple episodes from a season
    - TV Seasons: Single or multiple complete seasons
    - TV Shows: Entire show with all seasons
    
    Workflow:
    1. Validate request and retention policy
    2. Fetch TMDB metadata
    3. Check Plex for duplicates (dedupe detection)
    4. Check for existing requests from other users
    5. Create MediaRequest record with retention policy
    6. For each season/download needed:
       a. Search Prowlarr for torrents
       b. Score and select best torrent
       c. Add to qBittorrent
       d. Create Download record linked to MediaRequest
    7. Create EpisodeRetention overrides
    8. Trigger background monitoring
    9. [PLACEHOLDER] Send notification
    
    Returns:
        Comprehensive response with all created records
    """
    from src.plex import check_media_exists
    from src.TMDB import get_movie_details, get_tv_details
    from src.prowlarr import get_prowlarr_client, CATEGORY_MOVIES, CATEGORY_TV
    from src.scoring import rank_torrents, select_best_torrent
    
    print_info(f"[UNIFIED REQUEST] User {current_user.username} - TMDB {request.tmdb_id} ({request.media_type})", prefix="DOWNLOADS")
    
    try:
        # ====================================================================
        # Step 1: Validate Request
        # ====================================================================
        
        valid_retention = ['forever', 'watch_once', 'watch_as_released']
        if request.retention_type not in valid_retention:
            raise HTTPException(status_code=400, detail=f"Invalid retention_type. Must be one of: {valid_retention}")
        
        if request.retention_type == 'watch_as_released' and request.media_type != 'tv':
            raise HTTPException(status_code=400, detail="watch_as_released is only valid for TV shows")
        
        if request.media_type not in ['movie', 'tv']:
            raise HTTPException(status_code=400, detail="media_type must be 'movie' or 'tv'")
        
        if request.media_type == 'tv' and request.seasons is not None and len(request.seasons) == 0:
            raise HTTPException(status_code=400, detail="seasons list cannot be empty")
        
        # ====================================================================
        # Step 2: Fetch TMDB Metadata
        # ====================================================================
        
        print_info("[Step 1/9] Fetching TMDB metadata...", prefix="DOWNLOADS")
        if request.media_type == 'movie':
            tmdb_data = get_movie_details(request.tmdb_id)
            title = tmdb_data.get('title')
            year = tmdb_data.get('year')
        else:
            tmdb_data = get_tv_details(request.tmdb_id)
            title = tmdb_data.get('name')
            year = tmdb_data.get('year')
            seasons_data = tmdb_data.get('seasons', [])
        
        if not title:
            raise HTTPException(status_code=404, detail="Media not found on TMDB")
        
        print_info(f"Found: {title} ({year})", prefix="DOWNLOADS")
        
        # Detect anime for TV shows
        is_anime = False
        if request.media_type == 'tv':
            from src.TMDB import is_anime as detect_anime
            is_anime = detect_anime(tmdb_data)
            if is_anime:
                print_info("Detected as anime - will use ANIME_PATH if configured", prefix="DOWNLOADS")
        
        # ====================================================================
        # Step 3: Check Plex for Duplicates
        # ====================================================================
        
        print_info("[Step 2/9] Checking Plex for duplicates...", prefix="DOWNLOADS")
        
        if request.media_type == 'movie':
            plex_check = check_media_exists(
                tmdb_title=title,
                year=year,
                media_type='movie'
            )
            
            if plex_check.get('exists'):
                print_info("Movie already exists in Plex", prefix="DOWNLOADS")
                return UnifiedMediaRequestResponse(
                    status="already_exists",
                    message=f"{title} ({year}) already available in Plex",
                    plex_info=plex_check
                )
        else:
            # For TV shows, check what we need vs what exists
            seasons_to_request = []
            episodes_to_request = {}
            
            if request.seasons is None:
                # Request entire show - get all seasons from TMDB
                seasons_to_request = [s['season_number'] for s in seasons_data if s['season_number'] > 0]
            else:
                seasons_to_request = request.seasons
            
            # Build episodes map
            for season_num in seasons_to_request:
                if request.episodes and str(season_num) in request.episodes:
                    # Specific episodes requested
                    episodes_to_request[season_num] = request.episodes[str(season_num)]
                else:
                    # Full season requested
                    episodes_to_request[season_num] = None
            
            # Check each season against Plex
            all_exist = True
            missing_seasons = {}
            
            for season_num, requested_eps in episodes_to_request.items():
                plex_check = check_media_exists(
                    tmdb_title=title,
                    year=year,
                    media_type='tv',
                    season=season_num,
                    episodes=requested_eps
                )
                
                if not plex_check.get('exists'):
                    all_exist = False
                    missing_seasons[season_num] = requested_eps
                elif plex_check.get('partial') and plex_check.get('missing_episodes'):
                    all_exist = False
                    missing_seasons[season_num] = plex_check['missing_episodes']
            
            if all_exist:
                print_info("All requested content already exists in Plex", prefix="DOWNLOADS")
                return UnifiedMediaRequestResponse(
                    status="already_exists",
                    message=f"{title} - all requested content already available in Plex"
                )
            
            if missing_seasons:
                print_info(f"Partial match - will download missing: {missing_seasons}", prefix="DOWNLOADS")
                episodes_to_request = missing_seasons
            else:
                print_info("No existing content found in Plex, proceeding with full request", prefix="DOWNLOADS")
        
        # ====================================================================
        # Step 4: Check for Existing Requests
        # ====================================================================
        
        print_info("[Step 3/9] Checking for existing requests...", prefix="DOWNLOADS")
        # Get composite index key for tmdb_id and media_type
        index_key = f"{request.tmdb_id}__{request.media_type}"
        existing_requests = [r for r in media_request_store.list_by_index('tmdb_id__media_type', index_key)
                            if r.status != 'deleted']
        
        if existing_requests:
            effective_retention, protected = get_effective_retention(
                db, request.tmdb_id, request.media_type
            )
            print_info(f"Found {len(existing_requests)} existing request(s) - Effective retention: {effective_retention}", prefix="DOWNLOADS")
        
        # ====================================================================
        # Step 5: Create MediaRequest Record
        # ====================================================================
        
        print_info("[Step 4/9] Creating MediaRequest record...", prefix="DOWNLOADS")
        
        # Determine if we should track upcoming episodes
        track_upcoming = False
        if request.media_type == 'tv':
            if request.seasons is None:
                # Requesting entire show - track upcoming episodes
                track_upcoming = True
                print_info("Tracking upcoming episodes: entire show requested", prefix="DOWNLOADS")
            else:
                # Check if requesting the latest ongoing season
                ongoing_seasons = [s for s in tmdb_season_cache_store.list_by_index('tmdb_id', request.tmdb_id)
                                  if s.season_status == 'ongoing']
                
                if ongoing_seasons:
                    highest_ongoing = max(s.season_number for s in ongoing_seasons)
                    if highest_ongoing in seasons_to_request:
                        track_upcoming = True
                        print_info(f"Tracking upcoming episodes: latest ongoing season {highest_ongoing} requested", prefix="DOWNLOADS")
        
        media_request = MediaRequest(
            user_id=current_user.id,
            tmdb_id=request.tmdb_id,
            media_type=request.media_type,
            title=title,
            year=year,
            retention_type=request.retention_type,
            status='pending',  # Start as pending until downloads are added
            requested_at=datetime.utcnow(),
            requested_seasons=json.dumps(request.seasons) if request.seasons else None,
            track_upcoming=1 if track_upcoming else 0,
            is_anime=is_anime if request.media_type == 'tv' else None
        )
        
        media_request = media_request_store.save(media_request)
        media_request_id = media_request.id
        print_monitor({"media_request_id": media_request_id, "tmdb_id": request.tmdb_id, "media_type": request.media_type}, prefix="DOWNLOADS")
        
        # ====================================================================
        # Step 6: Create Episode Retention Overrides
        # ====================================================================
        
        if request.media_type == 'tv' and request.episode_retention_overrides:
            print_info("[Step 5/9] Creating episode retention overrides...", prefix="DOWNLOADS")
            for override in request.episode_retention_overrides:
                episode_retention = EpisodeRetention(
                    media_request_id=media_request_id,
                    season_number=override['season'],
                    episode_number=override['episode'],
                    retention_type=override['retention_type']
                )
                episode_retention_store.save(episode_retention)
            print_info(f"Created {len(request.episode_retention_overrides)} episode overrides", prefix="DOWNLOADS")
        
        # ====================================================================
        # Step 7: Download Torrents
        # ====================================================================
        
        print_info("[Step 6/9] Searching and downloading torrents...", prefix="DOWNLOADS")
        download_ids = []
        torrent_details = []
        
        qb = get_qbittorrent_client()
        prowlarr = get_prowlarr_client()
        
        failed_ids = download_store.get_ids_by_index_multi('status', ['failed', 'partial_failed'])
        failed_downloads = [download_store.load(id) for id in failed_ids if download_store.load(id)]
        failed_hashes = {d.torrent_hash.lower() for d in failed_downloads}
        
        # Get original language for dual audio scoring
        original_language = tmdb_data.get('original_language')
        
        if request.media_type == 'movie':
            success, download_id, torrent_info, error = await _download_torrent(
                prowlarr=prowlarr,
                qb=qb,
                media_type='movie',
                title=title,
                year=year,
                tmdb_id=request.tmdb_id,
                media_request_id=media_request_id,
                failed_hashes=failed_hashes,
                season=None,
                episodes=None,
                original_language=original_language,
                is_anime=False
            )
            
            if not success:
                # Re-query MediaRequest to update status
                media_request = media_request_store.load(media_request_id)
                if media_request:
                    media_request.status = 'failed'
                    media_request_store.save(media_request)
                
                print_error(f"[NOTIFICATION PLACEHOLDER] Notify user {current_user.username}: Request failed - {error}", prefix="DOWNLOADS")
                
                raise HTTPException(status_code=422, detail=error)
            
            download_ids.append(download_id)
            torrent_details.append(torrent_info)
        
        else:
            for season_num, requested_eps in episodes_to_request.items():
                print_info(f"Downloading Season {season_num} (episodes: {requested_eps or 'all'})", prefix="DOWNLOADS")
                
                success, download_id, torrent_info, error = await _download_torrent(
                    prowlarr=prowlarr,
                    qb=qb,
                    media_type='tv',
                    title=title,
                    year=year,
                    tmdb_id=request.tmdb_id,
                    media_request_id=media_request_id,
                    failed_hashes=failed_hashes,
                    season=season_num,
                    episodes=requested_eps,
                    original_language=original_language,
                    is_anime=is_anime
                )
                
                if not success:
                    print_error(f"Failed to download Season {season_num}: {error}", prefix="DOWNLOADS")
                    # Mark as partial on first failure (will update in Step 8)
                    torrent_details.append({
                        'season': season_num,
                        'status': 'failed',
                        'error': error
                    })
                else:
                    download_ids.append(download_id)
                    torrent_details.append(torrent_info)
        
        # ====================================================================
        # Step 8: Update MediaRequest Status
        # ====================================================================
        
        print_info("[Step 7/9] Updating MediaRequest status...", prefix="DOWNLOADS")
        media_request = media_request_store.load(media_request_id)
        if media_request:
            if len(download_ids) == 0:
                # No downloads succeeded
                media_request.status = 'failed'
            elif len(torrent_details) > len(download_ids):
                # Some downloads failed
                media_request.status = 'downloading'  # Partial success, still downloading
            else:
                # All downloads succeeded - now downloading
                media_request.status = 'downloading'
            media_request_store.save(media_request)
        
        # ====================================================================
        # Step 9: Notification Placeholder
        # ====================================================================
        
        print_info("[Step 8/9] [NOTIFICATION PLACEHOLDER] Sending notification...", prefix="DOWNLOADS")
        print_info(f"[NOTIFICATION PLACEHOLDER] Notify user {current_user.username}: '{title}' download started with {len(download_ids)} torrent(s)", prefix="DOWNLOADS")
        
        print_monitor({"status": "completed", "media_request_id": media_request_id, "downloads": download_ids, "user": current_user.username}, prefix="DOWNLOADS")
        
        return UnifiedMediaRequestResponse(
            status="success",
            message=f"{title} download{'s' if len(download_ids) > 1 else ''} started successfully",
            media_request_id=media_request_id,
            download_ids=download_ids,
            torrents=torrent_details
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print_error(f"[ERROR] Unified request failed: {e}", prefix="DOWNLOADS", exc_info=True)
        print_error(f"[NOTIFICATION PLACEHOLDER] Notify user {current_user.username}: Request error - {str(e)}", prefix="DOWNLOADS")
        raise HTTPException(status_code=500, detail=str(e))


async def _download_torrent(
    prowlarr, qb, media_type: str, title: str, year: int,
    tmdb_id: int, media_request_id: int, failed_hashes: set,
    season: Optional[int], episodes: Optional[List[int]],
    original_language: Optional[str] = None,
    is_anime: bool = False
) -> tuple:
    """
    Helper function to search, score, and download a single torrent.
    
    Returns:
        (success: bool, download_id: int|None, torrent_info: dict|None, error: str|None)
    """
    from src.prowlarr import CATEGORY_MOVIES, CATEGORY_TV
    from src.scoring import rank_torrents, select_best_torrent
    
    try:
        if media_type == 'movie':
            query = f"{normalize_title(title)} {year}"
            category = CATEGORY_MOVIES
        else:
            normalized_title = normalize_title(title)
            query = f"{normalized_title} S{season:02d}" if season else normalized_title
            category = CATEGORY_TV
        
        torrents = prowlarr.search(query, category)
        if not torrents:
            return (False, None, None, f"No torrents found for {title}")
        
        print_monitor({"torrents_found": len(torrents), "query": query}, prefix="DOWNLOADS")
        
        scored_torrents = rank_torrents(
            torrents=torrents,
            failed_hashes=failed_hashes,
            tmdb_id=tmdb_id if media_type == 'tv' else None,
            season_number=season,
            requested_episodes=episodes,
            qb_client=qb,
            original_language=original_language
        )
        
        if not scored_torrents:
            return (False, None, None, "No suitable torrents after filtering")
        
        best_torrent = select_best_torrent(scored_torrents)
        if not best_torrent:
            return (False, None, None, "No torrents meet minimum quality requirements")
        
        print_info(f"Selected: {best_torrent.torrent.title} (score: {best_torrent.final_score:.2f})", prefix="DOWNLOADS")
        
        # Helper function to validate torrent title matches the requested show
        def title_matches(torrent_title: str, expected_title: str) -> bool:
            """Check if torrent title matches the expected show/movie name."""
            import re
            
            # Normalize: lowercase, remove punctuation, collapse whitespace
            normalize = lambda s: ' '.join(re.sub(r'[^\w\s]', ' ', s.lower()).split())
            
            torrent_norm = normalize(torrent_title)
            expected_norm = normalize(expected_title)
            
            # Split into words, filter out short/common words
            stop_words = {'the', 'a', 'an', 'and', 'or', 'of', 'in', 'to', 'for', 's01', 's02', 's03', 's04', 's05', 's06', 's07', 's08', 's09', 's10'}
            get_words = lambda s: [w for w in s.split() if len(w) > 2 and w not in stop_words]
            
            expected_words = get_words(expected_norm)
            torrent_words = get_words(torrent_norm)
            
            if not expected_words:
                return True  # No significant words to match
            
            # Remove stop words from both strings for contiguous matching
            remove_stop_words = lambda s: ' '.join([w for w in s.split() if len(w) > 2 and w not in stop_words])
            torrent_filtered = remove_stop_words(torrent_norm)
            expected_filtered = remove_stop_words(expected_norm)
            
            # Check if expected title appears as contiguous sequence in torrent title
            # "Breaking Bad" should appear together, not scattered
            # This handles "Breaking Bad S01" ✓ but rejects "The Bad Guys Breaking In" ✗
            expected_pattern = r'\b' + r'\s+'.join(re.escape(w) for w in expected_words) + r'\b'
            if re.search(expected_pattern, torrent_filtered):
                return True
            
            # Fallback: at least 80% of expected words must be present AND
            # torrent shouldn't have more than 3 extra significant words
            matches = sum(1 for word in expected_words if word in torrent_words)
            match_ratio = matches / len(expected_words)
            extra_words = len([w for w in torrent_words if w not in expected_words])
            
            return match_ratio >= 0.8 and extra_words <= 3
        
        # Try top 20% of results with minimum 15
        # Don't count torrents without info_hash toward the limit
        max_download_attempts = max(int(len(scored_torrents) * 0.2), 15)

        # If there are fewer scored torrents than the max attempts, adjust the limit
        if len(scored_torrents) < max_download_attempts:
            max_download_attempts = len(scored_torrents)

        actual_attempts = 0
        torrent_index = 0
        
        while actual_attempts < max_download_attempts and torrent_index < len(scored_torrents):
            best_torrent = scored_torrents[torrent_index]
            
            if torrent_index > 0:
                print_info(f"[Torrent Fallback {actual_attempts}/{max_download_attempts}] Trying: {best_torrent.torrent.title}", prefix="DOWNLOADS")
            
            torrent_index += 1  # Always increment to move to next torrent
            
            # Validate title matches BEFORE checking info hash
            if not title_matches(best_torrent.torrent.title, title):
                print_warning(f"Torrent title mismatch: '{best_torrent.torrent.title}' doesn't match '{title}', skipping (not counted toward limit)", prefix="DOWNLOADS")
                continue
            
            # Check for multi-season packs when requesting a single season
            # Import here to avoid circular dependency
            from src.scoring import is_multi_season_pack
            if is_multi_season_pack(best_torrent.torrent.title):
                print_warning(f"Multi-season pack detected: '{best_torrent.torrent.title}' - rejecting (single season requested), skipping (not counted toward limit)", prefix="DOWNLOADS")
                continue
            
            try:
                # Use info_hash from Prowlarr if available, otherwise extract from magnet
                info_hash = best_torrent.torrent.info_hash
                if not info_hash:
                    info_hash = QBittorrentClient.extract_info_hash(best_torrent.torrent.magnet_link)
                
                if not info_hash:
                    print_warning(f"Could not get info hash for torrent, skipping (not counted toward limit)", prefix="DOWNLOADS")
                    continue
                
                # Count this as an actual attempt since we have a valid hash
                actual_attempts += 1
                
                # Check if torrent already exists (with IntegrityError handling)
                try:
                    existing = download_store.find_by_index('torrent_hash', info_hash)
                    if existing:
                        print_info(f"Found existing Download ID {existing.id} - verifying in qBittorrent...", prefix="DOWNLOADS")
                        
                        # Verify torrent actually exists in qBittorrent
                        try:
                            qb_torrent = qb.get_torrent_info(info_hash)
                            if qb_torrent:
                                print_info(f"✓ Torrent exists in qBittorrent - reusing Download ID {existing.id}", prefix="DOWNLOADS")
                                
                                if not existing.media_request_id:
                                    existing.media_request_id = media_request_id
                                    download_store.save(existing)
                                
                                return (True, existing.id, {
                                    'title': best_torrent.torrent.title,
                                    'size_gb': best_torrent.torrent.size_gb,
                                    'seeders': best_torrent.torrent.seeders,
                                    'score': best_torrent.final_score,
                                    'indexer': best_torrent.torrent.indexer,
                                    'existing': True
                                }, None)
                            else:
                                print_warning(f"Download {existing.id} exists in DB but not in qBittorrent - trying next torrent", prefix="DOWNLOADS")
                                # Don't return, continue to next torrent
                        except Exception as qb_error:
                            print_warning(f"Error verifying torrent in qBittorrent: {qb_error} - trying next torrent", prefix="DOWNLOADS")
                            # Don't return, continue to next torrent
                except Exception as e:
                    print_warning(f"Error checking existing torrent: {e}", prefix="DOWNLOADS")
                
                # Add to qBittorrent
                category = media_type
                
                # Determine save path - use ANIME_PATH for anime TV shows if configured
                anime_path = os.getenv('ANIME_PATH')
                if is_anime and anime_path and anime_path != 'no-anime-setup':
                    save_path = anime_path
                    print_info(f"Using anime path: {save_path}", prefix="DOWNLOADS")
                else:
                    save_path = os.getenv('DOWNLOADS_PATH')
                
                print_info(f"[ATTEMPT {actual_attempts}/{max_download_attempts}] Adding magnet to qBittorrent...", prefix="DOWNLOADS")
                print_debug(f"  Category: {category}, Save path: {save_path}", prefix="DOWNLOADS")
                print_debug(f"  Magnet link: {best_torrent.torrent.magnet_link[:100]}...", prefix="DOWNLOADS")
                
                success = qb.add_magnet(
                    best_torrent.torrent.magnet_link,
                    category=category,
                    save_path=save_path
                )
                
                if not success:
                    print_warning(f"qBittorrent failed to accept magnet, trying next torrent", prefix="DOWNLOADS")
                    failed_hashes.add(info_hash)
                    continue
                
                print_info(f"✓ Magnet accepted by qBittorrent", prefix="DOWNLOADS")
                
                # Wait for torrent to connect with progressive retry (10s×3, 30s×1, 60s×1)
                print_info(f"Waiting for torrent to connect and retrieve metadata...", prefix="DOWNLOADS")
                print_debug(f"About to await await_torrent_connection for hash: {info_hash}", prefix="DOWNLOADS")
                
                connection_success, torrent_info, files = await await_torrent_connection(qb, info_hash)
                
                print_debug(f"await_torrent_connection returned: success={connection_success}, info={torrent_info is not None}, files={files is not None}", prefix="DOWNLOADS")
                
                if not connection_success or not torrent_info or not files:
                    print_warning(f"Failed to connect to torrent after all retries, trying next torrent", prefix="DOWNLOADS")
                    qb.delete_torrent(info_hash, delete_files=True)
                    failed_hashes.add(info_hash)
                    continue
                
                # Validate files
                validation = validate_torrent_files(files)
                if not validation.valid:
                    print_warning(f"Torrent validation failed: {validation.reason}", prefix="DOWNLOADS")
                    qb.delete_torrent(info_hash, delete_files=True)
                    failed_hashes.add(info_hash)
                    continue
                
                # Success! Create download record with IntegrityError handling
                timeout_date = datetime.utcnow() + timedelta(days=15)
                
                # Format name with year for proper folder structure
                formatted_name = f"{title} ({year})" if year else title
                
                try:
                    download = Download(
                        torrent_hash=info_hash,
                        magnet_link=best_torrent.torrent.magnet_link,
                        status='downloading',
                        media_type=media_type,
                        metadata_json=json.dumps({
                            'name': formatted_name,  # Use formatted name with year
                            'size': torrent_info.get('size'),
                            'num_files': len(files),
                            'indexer': best_torrent.torrent.indexer,
                            'score': best_torrent.final_score
                        }),
                        will_timeout_at=timeout_date,
                        tmdb_id=tmdb_id,
                        year=year,
                        season=season,
                        episodes=json.dumps(episodes) if episodes else None,
                        media_request_id=media_request_id
                    )
                    
                    download = download_store.save(download)
                    download_id = download.id
                    
                    if media_type == 'tv' and season:
                        season_req = SeasonRequest(
                            download_id=download.id,
                            season_number=season,
                            episode_numbers=json.dumps(episodes) if episodes else None,
                            status='pending'
                        )
                        season_request_store.save(season_req)
                    
                    print_monitor({"download_id": download_id, "status": "created", "torrent_title": best_torrent.torrent.title}, prefix="DOWNLOADS")
                    
                    return (True, download_id, {
                        'title': best_torrent.torrent.title,
                        'size_gb': best_torrent.torrent.size_gb,
                        'seeders': best_torrent.torrent.seeders,
                        'score': best_torrent.final_score,
                        'indexer': best_torrent.torrent.indexer,
                        'resolution': best_torrent.resolution,
                        'episode_count': best_torrent.episode_count,
                        'season': season
                    }, None)
                
                except Exception as e:
                    # Handle any errors during save
                    print_error(f"Error creating Download: {e}", prefix="DOWNLOADS")
                    # Check if it was created by another concurrent request
                    existing = download_store.find_by_index('torrent_hash', info_hash)
                    if existing:
                        print_info(f"Download created by concurrent request - using existing Download ID: {existing.id}", prefix="DOWNLOADS")
                        if not existing.media_request_id:
                            existing.media_request_id = media_request_id
                            download_store.save(existing)
                        
                        return (True, existing.id, {
                            'title': best_torrent.torrent.title,
                            'size_gb': best_torrent.torrent.size_gb,
                            'seeders': best_torrent.torrent.seeders,
                            'score': best_torrent.final_score,
                            'indexer': best_torrent.torrent.indexer,
                            'existing': True
                        }, None)
                    else:
                        print_error(f"Error occurred but no existing download found: {e}", prefix="DOWNLOADS")
                        failed_hashes.add(info_hash)
                        continue
            
            except Exception as e:
                print_error(f"[Attempt {actual_attempts}/{max_download_attempts}] Error: {e}", prefix="DOWNLOADS")
                failed_hashes.add(info_hash) if info_hash else None
                continue
        
        # Determine appropriate error message
        if actual_attempts >= max_download_attempts:
            return (False, None, None, f"All {actual_attempts} torrent attempts failed")
        else:
            return (False, None, None, f"Exhausted all {torrent_index} available torrents ({actual_attempts} actual attempts)")
    
    except Exception as e:
        print_error(f"Download torrent error: {e}", prefix="DOWNLOADS")
        return (False, None, None, str(e))


@router.post("/media/search", response_model=dict)
async def search_media(
    request: MediaRequestModel
):
    """
    Preview torrent search results without downloading.
    
    Returns scored and ranked torrents for user review.
    
    Args:
        request: Media search request
        db: Database session
        
    Returns:
        dict with results list and metadata
    """
    from src.TMDB import get_movie_details, get_tv_details
    from src.prowlarr import get_prowlarr_client, CATEGORY_MOVIES, CATEGORY_TV
    from src.scoring import rank_torrents
    
    print_info(f"Media search preview: TMDB {request.tmdb_id} ({request.media_type})", prefix="DOWNLOADS")
    
    try:
        # Get TMDB metadata
        if request.media_type == 'movie':
            tmdb_data = get_movie_details(request.tmdb_id)
            title = tmdb_data.get('title')
            year = tmdb_data.get('year')
        else:
            tmdb_data = get_tv_details(request.tmdb_id)
            title = tmdb_data.get('name')
            year = tmdb_data.get('year')
        
        if not title:
            raise HTTPException(status_code=404, detail="Media not found on TMDB")
        
        # Search Prowlarr
        prowlarr = get_prowlarr_client()
        
        if request.media_type == 'movie':
            query = f"{normalize_title(title)} {year}"
            category = CATEGORY_MOVIES
        else:
            normalized_title = normalize_title(title)
            query = f"{normalized_title} S{request.season:02d}" if request.season else normalized_title
            category = CATEGORY_TV
        
        torrents = prowlarr.search(query, category)
        
        if not torrents:
            return {
                "results": [],
                "total_found": 0,
                "filtered_out": 0,
                "query": query
            }
        
        # Get failed hashes
        failed_ids = download_store.get_ids_by_index_multi('status', ['failed', 'partial_failed'])
        failed_downloads = [download_store.load(id) for id in failed_ids if download_store.load(id)]
        failed_hashes = {d.torrent_hash.lower() for d in failed_downloads}
        
        # Score torrents
        qb = get_qbittorrent_client()
        
        # Get original language for dual audio scoring
        original_language = tmdb_data.get('original_language')
        
        scored_torrents = rank_torrents(
            torrents=torrents,
            failed_hashes=failed_hashes,
            tmdb_id=request.tmdb_id if request.media_type == 'tv' else None,
            season_number=request.season,
            requested_episodes=request.episodes,
            qb_client=qb,
            original_language=original_language
        )
        
        # Format results
        results = []
        for scored in scored_torrents[:20]:  # Limit to top 20
            results.append({
                "title": scored.torrent.title,
                "size_gb": round(scored.torrent.size_gb, 2),
                "seeders": scored.torrent.seeders,
                "leechers": scored.torrent.leechers,
                "score": round(scored.final_score, 2),
                "indexer": scored.torrent.indexer,
                "is_season_pack": scored.is_season_pack,
                "episode_count": scored.episode_count,
                "resolution": scored.resolution,
                "reason": scored.reason
            })
        
        recommended = None
        if scored_torrents:
            best = scored_torrents[0]
            recommended = {
                "title": best.torrent.title,
                "reason": f"Highest score ({best.final_score:.1f}) with {best.torrent.seeders} seeders"
            }
        
        return {
            "results": results,
            "total_found": len(torrents),
            "filtered_out": len(torrents) - len(scored_torrents),
            "recommended": recommended,
            "query": query
        }
    
    except Exception as e:
        print_error(f"Media search failed: {e}", prefix="DOWNLOADS")
        raise HTTPException(status_code=500, detail=str(e))

