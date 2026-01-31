"""
Downloads API router for qBittorrent torrent management.
Provides endpoints for adding, monitoring, and managing downloads.
"""

import os
import json
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database import get_db
from src.models import Download
from src.qbittorrent import get_qbittorrent_client, QBittorrentClient
from src.torrent_validator import validate_torrent_files


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
