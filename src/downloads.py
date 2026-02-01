"""
Downloads API router for qBittorrent torrent management.
Provides endpoints for adding, monitoring, and managing downloads.
Includes media request workflow with Prowlarr integration.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database import get_db
from src.models import Download, SeasonRequest
from src.qbittorrent import get_qbittorrent_client, QBittorrentClient
from src.torrent_validator import validate_torrent_files

logger = logging.getLogger(__name__)


router = APIRouter()


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
    request: AddDownloadRequest,
    db: Session = Depends(get_db)
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
    existing = db.query(Download).filter(Download.torrent_hash == info_hash).first()
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
    
    db.add(download)
    db.commit()
    db.refresh(download)
    
    # Convert to response using to_dict
    download_dict = download.to_dict()
    return DownloadResponse(**download_dict)


@router.get("/downloads", response_model=List[DownloadResponse])
async def list_downloads(
    status: Optional[str] = None,
    media_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    List all downloads with optional filtering.
    Returns database snapshot only (no real-time qBittorrent queries).
    """
    query = db.query(Download)
    
    if status:
        query = query.filter(Download.status == status)
    
    if media_type:
        query = query.filter(Download.media_type == media_type)
    
    downloads = query.order_by(Download.added_at.desc()).all()
    
    return [DownloadResponse(**d.to_dict()) for d in downloads]


@router.get("/downloads/{download_id}", response_model=DownloadResponse)
async def get_download(
    download_id: int,
    db: Session = Depends(get_db)
):
    """Get detailed information about a specific download."""
    download = db.query(Download).filter(Download.id == download_id).first()
    
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    
    return DownloadResponse(**download.to_dict())


@router.delete("/downloads/{download_id}")
async def delete_download(
    download_id: int,
    delete_files: bool = False,
    db: Session = Depends(get_db)
):
    """
    Delete a download and optionally remove from qBittorrent.
    
    Args:
        download_id: Download ID
        delete_files: Whether to also delete files from disk
    """
    download = db.query(Download).filter(Download.id == download_id).first()
    
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    
    qb = get_qbittorrent_client()
    
    # Remove from qBittorrent if still active
    if download.status in ['downloading', 'seeding', 'pending']:
        qb.delete_torrent(str(download.torrent_hash), delete_files=delete_files)
    
    # Delete from database
    db.delete(download)
    db.commit()
    
    return {"message": "Download deleted successfully"}


@router.get("/downloads/failed-hashes", response_model=List[str])
async def get_failed_hashes(db: Session = Depends(get_db)):
    """
    Get list of info hashes for failed downloads.
    Used by requesting system to exclude problematic magnets.
    """
    failed_downloads = db.query(Download).filter(
        Download.status.in_(['failed', 'partial_failed'])
    ).all()
    
    return [d.torrent_hash for d in failed_downloads]


@router.post("/downloads/{download_id}/pause")
async def pause_download(
    download_id: int,
    db: Session = Depends(get_db)
):
    """Pause a download in qBittorrent."""
    download = db.query(Download).filter(Download.id == download_id).first()
    
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
    download_id: int,
    db: Session = Depends(get_db)
):
    """Resume a paused download in qBittorrent."""
    download = db.query(Download).filter(Download.id == download_id).first()
    
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
    request: MediaRequestModel,
    db: Session = Depends(get_db)
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
    
    logger.info(f"Media request: TMDB {request.tmdb_id} ({request.media_type})")
    
    try:
        # Step 1: Get TMDB metadata
        logger.info("Fetching TMDB metadata...")
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
        
        logger.info(f"Found: {title} ({year})")
        
        # Step 2: Check Plex for existing media
        logger.info("Checking Plex for duplicates...")
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
                logger.info(f"Partial match in Plex, requesting missing episodes: {missing_eps}")
                request.episodes = missing_eps
            else:
                # Media fully exists
                logger.info("Media already exists in Plex")
                return MediaRequestResponse(
                    status="already_exists",
                    message=f"{title} already available in Plex",
                    plex_info=plex_check
                )
        
        # Step 3: Search Prowlarr
        logger.info("Searching Prowlarr...")
        prowlarr = get_prowlarr_client()
        
        # Build search query
        if request.media_type == 'movie':
            query = f"{title} {year}"
            category = CATEGORY_MOVIES
        else:
            query = f"{title} S{request.season:02d}" if request.season else title
            category = CATEGORY_TV
        
        torrents = prowlarr.search(query, category)
        
        if not torrents:
            raise HTTPException(status_code=422, detail=f"No torrents found for {title}")
        
        logger.info(f"Found {len(torrents)} torrents from Prowlarr")
        
        # Step 4: Get failed hashes to exclude
        failed_downloads = db.query(Download).filter(
            Download.status.in_(['failed', 'partial_failed'])
        ).all()
        failed_hashes = {d.torrent_hash.lower() for d in failed_downloads}
        
        # Step 5: Score and rank torrents
        logger.info("Scoring torrents...")
        qb = get_qbittorrent_client()
        
        scored_torrents = rank_torrents(
            torrents=torrents,
            failed_hashes=failed_hashes,
            tmdb_id=request.tmdb_id if request.media_type == 'tv' else None,
            season_number=request.season,
            requested_episodes=request.episodes,
            db_session=db,
            qb_client=qb
        )
        
        if not scored_torrents:
            raise HTTPException(status_code=422, detail="No suitable torrents found after filtering")
        
        # Step 6: Select best torrent with fallback retry
        best_torrent = select_best_torrent(scored_torrents)
        
        if not best_torrent:
            raise HTTPException(status_code=422, detail="No torrents meet minimum quality requirements")
        
        logger.info(f"Selected: {best_torrent.torrent.title} (score: {best_torrent.final_score:.2f})")
        
        # Step 7: Add to qBittorrent
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Extract info hash
                info_hash = QBittorrentClient.extract_info_hash(best_torrent.torrent.magnet_link)
                if not info_hash:
                    raise ValueError("Could not extract info hash from magnet")
                
                # Check for duplicates
                existing = db.query(Download).filter(Download.torrent_hash == info_hash).first()
                if existing:
                    logger.info(f"Torrent already in downloads: {existing.id}")
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
                
                db.add(download)
                db.commit()
                db.refresh(download)
                
                logger.info(f"Download added successfully: ID {download.id}")
                
                # Create SeasonRequest if TV show
                if request.media_type == 'tv' and request.season:
                    season_req = SeasonRequest(
                        download_id=download.id,
                        season_number=request.season,
                        episode_numbers=json.dumps(request.episodes) if request.episodes else None,
                        status='pending'
                    )
                    db.add(season_req)
                    db.commit()
                
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
                logger.error(f"Attempt {attempt + 1} failed: {e}")
                
                if attempt < max_attempts - 1:
                    # Try next best torrent
                    if attempt + 1 < len(scored_torrents):
                        best_torrent = scored_torrents[attempt + 1]
                        logger.info(f"Retrying with next torrent: {best_torrent.torrent.title}")
                    else:
                        raise HTTPException(status_code=500, detail=f"All torrents failed: {str(e)}")
                else:
                    raise HTTPException(status_code=500, detail=f"Failed to add download: {str(e)}")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Media request failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/media/search", response_model=dict)
async def search_media(
    request: MediaRequestModel,
    db: Session = Depends(get_db)
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
    
    logger.info(f"Media search preview: TMDB {request.tmdb_id} ({request.media_type})")
    
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
            query = f"{title} {year}"
            category = CATEGORY_MOVIES
        else:
            query = f"{title} S{request.season:02d}" if request.season else title
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
        failed_downloads = db.query(Download).filter(
            Download.status.in_(['failed', 'partial_failed'])
        ).all()
        failed_hashes = {d.torrent_hash.lower() for d in failed_downloads}
        
        # Score torrents
        qb = get_qbittorrent_client()
        
        scored_torrents = rank_torrents(
            torrents=torrents,
            failed_hashes=failed_hashes,
            tmdb_id=request.tmdb_id if request.media_type == 'tv' else None,
            season_number=request.season,
            requested_episodes=request.episodes,
            db_session=db,
            qb_client=qb
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
        logger.error(f"Media search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

