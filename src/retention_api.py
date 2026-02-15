"""
Retention system API endpoints.
Handles media requests with retention policies, scheduled deletions, and settings management.
"""

from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.database import get_db
from src.auth import get_current_user, require_admin
from src.models import User, Settings
from src.pickle_models import MediaRequest, EpisodeRetention, Download
from src.pickle_stores import media_request_store, episode_retention_store, download_store
from src.retention import (
    get_effective_retention,
    schedule_deletion,
    schedule_episode_deletion,
    recalculate_deletion_schedule,
    get_scheduled_deletions,
    get_scheduled_episode_deletions,
    cancel_scheduled_deletion,
    get_grace_period_days
)
from src.audit import log_action
from src.console import print_info


router = APIRouter(prefix="/api", tags=["retention"])


# Request Models
class EpisodeOverride(BaseModel):
    season: int = Field(..., ge=1, description="Season number")
    episode: int = Field(..., ge=1, description="Episode number")
    retention_type: str = Field(..., pattern="^(forever|watch_once|watch_as_released)$")


class MediaRequestCreate(BaseModel):
    tmdb_id: int = Field(..., gt=0)
    media_type: str = Field(..., pattern="^(movie|tv)$")
    title: str = Field(..., min_length=1, max_length=255)
    year: Optional[int] = Field(None, ge=1800, le=2100)
    retention_type: str = Field(default="watch_once", pattern="^(forever|watch_once|watch_as_released)$")
    episode_retention_overrides: Optional[List[EpisodeOverride]] = Field(default=None)


class MediaRequestUpdate(BaseModel):
    retention_type: str = Field(..., pattern="^(forever|watch_once|watch_as_released)$")


class ManageRequestCreate(BaseModel):
    """Simplified request model for managing already-available media."""
    tmdb_id: int = Field(..., gt=0)
    media_type: str = Field(..., pattern="^(movie|tv)$")
    retention_type: str = Field(default="watch_once", pattern="^(forever|watch_once|watch_as_released)$")


class RetentionSettingsUpdate(BaseModel):
    watch_once_grace_days: Optional[int] = Field(None, ge=1, le=365)
    watch_as_released_grace_days: Optional[int] = Field(None, ge=1, le=365)


# Response Models
class MediaRequestResponse(BaseModel):
    id: int
    user_id: int
    tmdb_id: int
    media_type: str
    title: str
    year: Optional[int]
    retention_type: str
    auto_delete_enabled: bool
    watched_at: Optional[datetime]
    deletion_scheduled_at: Optional[datetime]
    status: str
    requested_at: datetime
    completed_at: Optional[datetime]
    deleted_at: Optional[datetime]

    class Config:
        from_attributes = True


# Endpoints

@router.post("/requests", response_model=MediaRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_media_request(
    request_data: MediaRequestCreate,
    current_user: User = Depends(get_current_user)
):
    """
    Create a new media request with retention policy.
    Handles multi-user retention logic and episode overrides for TV shows.
    """
    # Validate watch_as_released only for TV shows
    if request_data.retention_type == 'watch_as_released' and request_data.media_type != 'tv':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="watch_as_released retention type is only valid for TV shows"
        )
    
    # Check for existing requests
    index_key = f"{request_data.tmdb_id}__{request_data.media_type}"
    existing_requests = [
        r for r in media_request_store.list_by_index('tmdb_id__media_type', index_key)
        if r.status != 'deleted'
    ]
    
    # Determine effective retention across all users
    effective_retention, protected = get_effective_retention(
        None, request_data.tmdb_id, request_data.media_type
    )
    
    # Create new media request
    media_request = MediaRequest(
        user_id=current_user.id,
        tmdb_id=request_data.tmdb_id,
        media_type=request_data.media_type,
        title=request_data.title,
        year=request_data.year,
        retention_type=request_data.retention_type,
        status='pending'
    )
    
    media_request = media_request_store.save(media_request)
    
    # Create episode retention overrides for TV shows
    if request_data.media_type == 'tv' and request_data.episode_retention_overrides:
        for override in request_data.episode_retention_overrides:
            episode_retention = EpisodeRetention(
                media_request_id=media_request.id,
                season_number=override.season,
                episode_number=override.episode,
                retention_type=override.retention_type
            )
            episode_retention_store.save(episode_retention)
    
    # Log retention conflict if exists
    if existing_requests:
        new_effective, _ = get_effective_retention(
            None, request_data.tmdb_id, request_data.media_type
        )
        if new_effective != effective_retention:
            print_info(f"Retention conflict resolved for {request_data.title}: "
                  f"{effective_retention} -> {new_effective}", prefix="Retention")
    
    return media_request


@router.get("/requests", response_model=List[MediaRequestResponse])
async def list_media_requests(
    media_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user)
):
    """List user's media requests with optional filters."""
    all_requests = media_request_store.list_by_index('user_id', current_user.id)
    
    # Apply filters
    filtered = all_requests
    if media_type:
        filtered = [r for r in filtered if r.media_type == media_type]
    if status:
        filtered = [r for r in filtered if r.status == status]
    
    # Sort by requested_at descending
    filtered.sort(key=lambda r: r.requested_at if r.requested_at else datetime.min, reverse=True)
    
    # Apply pagination
    requests = filtered[offset:offset+limit]
    
    return requests


@router.get("/requests/by-media")
async def get_request_by_media(
    tmdb_id: int,
    current_user: User = Depends(get_current_user)
):
    """Get user's request for specific media by TMDB ID."""
    user_requests = media_request_store.list_by_index('user_id', current_user.id)
    media_request = next(
        (r for r in user_requests if r.tmdb_id == tmdb_id and r.status != 'deleted'),
        None
    )
    
    if not media_request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    
    # Get episode overrides if TV show
    episode_overrides = []
    if media_request.media_type == 'tv':
        overrides = episode_retention_store.list_by_index('media_request_id', media_request.id)
        episode_overrides = [override.to_dict() for override in overrides]
    
    return {
        **media_request.to_dict(),
        "episode_overrides": episode_overrides
    }


@router.get("/requests/{request_id}", response_model=dict)
async def get_media_request(
    request_id: int,
    current_user: User = Depends(get_current_user)
):
    """Get detailed information about a specific request."""
    media_request = media_request_store.load(request_id)
    
    if not media_request or media_request.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    
    # Get episode overrides if TV show
    episode_overrides = []
    if media_request.media_type == 'tv':
        overrides = episode_retention_store.list_by_index('media_request_id', request_id)
        episode_overrides = [override.to_dict() for override in overrides]
    
    # Get effective retention
    effective_retention, protected = get_effective_retention(
        None, media_request.tmdb_id, media_request.media_type
    )
    
    return {
        **media_request.to_dict(),
        "effective_retention": effective_retention,
        "protected": protected,
        "episode_overrides": episode_overrides
    }




@router.post("/manage")
async def create_available_request(
    request_data: ManageRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a request for media that's already available in Plex.
    Sets status to 'available' and bypasses download workflow.
    """
    from src.plex import check_media_exists
    from src.TMDB import get_movie_details, get_tv_details
    
    # Validate watch_as_released only for TV shows
    if request_data.retention_type == 'watch_as_released' and request_data.media_type != 'tv':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="watch_as_released retention type is only valid for TV shows"
        )
    
    # Get media details from TMDB
    if request_data.media_type == 'movie':
        details = get_movie_details(request_data.tmdb_id)
    else:
        details = get_tv_details(request_data.tmdb_id)
    
    title = details.get('title') or details.get('name', 'Unknown')
    year = details.get('year')
    
    # Verify media exists in Plex
    plex_check = check_media_exists(title, year, request_data.media_type)
    if not plex_check.get('exists'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Media not found in Plex library"
        )
    
    # Check for existing request
    user_requests = media_request_store.list_by_index('user_id', current_user.id)
    existing = next(
        (r for r in user_requests if r.tmdb_id == request_data.tmdb_id and r.status != 'deleted'),
        None
    )
    
    if existing:
        return existing.to_dict()
    
    # Create new request with status='available'
    media_request = MediaRequest(
        user_id=current_user.id,
        tmdb_id=request_data.tmdb_id,
        media_type=request_data.media_type,
        title=title,
        year=year,
        retention_type=request_data.retention_type,
        status='available',
        completed_at=datetime.utcnow()
    )
    
    media_request = media_request_store.save(media_request)
    
    print_info(f"Created available request for {title} (User: {current_user.username})", prefix="Request")
    
    return media_request.to_dict()


@router.put("/requests/{request_id}/retention", response_model=MediaRequestResponse)
async def update_retention_type(
    request_id: int,
    update_data: MediaRequestUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update retention type for a request with audit logging."""
    media_request = media_request_store.load(request_id)
    
    if not media_request or media_request.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    
    # Validate watch_as_released only for TV shows
    if update_data.retention_type == 'watch_as_released' and media_request.media_type != 'tv':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="watch_as_released retention type is only valid for TV shows"
        )
    
    # Capture old state for audit log
    old_retention = media_request.retention_type
    
    # Update retention type
    media_request.retention_type = update_data.retention_type
    
    # Recalculate deletion schedule
    recalculate_deletion_schedule(None, media_request)
    
    media_request_store.save(media_request)
    
    # Log the change
    log_action(
        db=db,
        user_id=current_user.id,
        action_type='retention_change',
        entity_type='media_request',
        entity_id=request_id,
        old_value={'retention_type': old_retention},
        new_value={'retention_type': update_data.retention_type},
        description=f"Changed retention for '{media_request.title}' from {old_retention} to {update_data.retention_type}",
        request=request
    )
    
    db.refresh(media_request)
    
    print_info(f"Retention updated for {media_request.title}: {old_retention} -> {update_data.retention_type}", prefix="Retention")
    
    return media_request


@router.put("/requests/{request_id}/episodes/{season}/{episode}/retention")
async def set_episode_retention(
    request_id: int,
    season: int,
    episode: int,
    update_data: MediaRequestUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Set retention override for a specific episode."""
    media_request = media_request_store.load(request_id)
    
    if not media_request or media_request.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    
    if media_request.media_type != 'tv':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Episode retention is only valid for TV shows"
        )
    
    # Get or create episode retention
    all_ep_retentions = episode_retention_store.list_by_index('media_request_id', request_id)
    episode_retention = next(
        (ep for ep in all_ep_retentions if ep.season_number == season and ep.episode_number == episode),
        None
    )
    
    if episode_retention:
        episode_retention.retention_type = update_data.retention_type
    else:
        episode_retention = EpisodeRetention(
            media_request_id=request_id,
            season_number=season,
            episode_number=episode,
            retention_type=update_data.retention_type
        )
    
    episode_retention = episode_retention_store.save(episode_retention)
    
    # Recalculate episode deletion schedule
    schedule_episode_deletion(None, media_request, season, episode)
    
    return {"message": "Episode retention updated", "episode": episode_retention.to_dict()}


@router.get("/scheduled-deletions")
async def get_user_scheduled_deletions(
    media_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user)
):
    """Get user's upcoming scheduled deletions."""
    deletions = get_scheduled_deletions(
        None,
        user_id=current_user.id,
        media_type=media_type,
        limit=limit,
        offset=offset
    )
    
    return {
        "deletions": deletions,
        "total": len(deletions)
    }


@router.delete("/scheduled-deletions/{request_id}/cancel")
async def cancel_deletion(
    request_id: int,
    current_user: User = Depends(get_current_user)
):
    """Cancel a scheduled deletion."""
    media_request = media_request_store.load(request_id)
    
    if not media_request or media_request.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    
    success = cancel_scheduled_deletion(None, request_id)
    
    if success:
        return {"message": "Deletion cancelled successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel deletion"
        )


# Settings Endpoints

@router.get("/settings/retention")
async def get_retention_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get retention grace period settings."""
    watch_once_days = get_grace_period_days(db, 'watch_once')
    watch_as_released_days = get_grace_period_days(db, 'watch_as_released')
    
    return {
        "watch_once_grace_days": watch_once_days,
        "watch_as_released_grace_days": watch_as_released_days
    }


@router.put("/settings/retention")
async def update_retention_settings(
    settings: RetentionSettingsUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update retention grace period settings (admin only)."""
    updated = []
    
    if settings.watch_once_grace_days is not None:
        setting = db.query(Settings).filter(Settings.key == 'watch_once_grace_days').first()
        if setting:
            setting.value = str(settings.watch_once_grace_days)
            setting.updated_at = datetime.utcnow()
        else:
            setting = Settings(
                key='watch_once_grace_days',
                value=str(settings.watch_once_grace_days),
                description='Grace period in days before deleting watch_once media after first view'
            )
            db.add(setting)
        updated.append('watch_once_grace_days')
    
    if settings.watch_as_released_grace_days is not None:
        setting = db.query(Settings).filter(Settings.key == 'watch_as_released_grace_days').first()
        if setting:
            setting.value = str(settings.watch_as_released_grace_days)
            setting.updated_at = datetime.utcnow()
        else:
            setting = Settings(
                key='watch_as_released_grace_days',
                value=str(settings.watch_as_released_grace_days),
                description='Grace period in days before deleting watch_as_released episodes after being watched'
            )
            db.add(setting)
        updated.append('watch_as_released_grace_days')
    
    db.commit()
    
    return {
        "message": "Settings updated successfully",
        "updated": updated
    }


# Admin Endpoints

@router.get("/admin/scheduled-deletions")
async def get_all_scheduled_deletions(
    media_type: Optional[str] = None,
    retention_type: Optional[str] = None,
    user_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(require_admin)
):
    """View all scheduled deletions across all users (admin only)."""
    all_requests = media_request_store.list_all()
    
    # Filter for scheduled deletions
    scheduled = [
        r for r in all_requests
        if r.deletion_scheduled_at is not None
        and r.auto_delete_enabled == 1
        and r.status != 'deleted'
    ]
    
    # Apply additional filters
    filtered = scheduled
    if media_type:
        filtered = [r for r in filtered if r.media_type == media_type]
    if retention_type:
        filtered = [r for r in filtered if r.retention_type == retention_type]
    if user_id:
        filtered = [r for r in filtered if r.user_id == user_id]
    
    # Sort by deletion_scheduled_at ascending
    filtered.sort(key=lambda r: r.deletion_scheduled_at if r.deletion_scheduled_at else datetime.max)
    
    # Apply pagination
    requests = filtered[offset:offset+limit]
    
    results = []
    for request in requests:
        effective_retention, _ = get_effective_retention(
            None, request.tmdb_id, request.media_type
        )
        
        data = request.to_dict()
        data['effective_retention'] = effective_retention
        data['days_until_deletion'] = (request.deletion_scheduled_at - datetime.utcnow()).days if request.deletion_scheduled_at else None
        results.append(data)
    
    return {
        "deletions": results,
        "total": len(results)
    }


@router.get("/admin/retention/stats")
async def get_retention_stats(
    current_user: User = Depends(require_admin)
):
    """Get retention system statistics (admin only)."""
    from datetime import timedelta
    
    all_requests = media_request_store.list_all()
    active_requests = [r for r in all_requests if r.status != 'deleted']
    
    total_requests = len(active_requests)
    
    # Count by retention type
    by_retention = {}
    for retention_type in ['forever', 'watch_once', 'watch_as_released']:
        count = len([r for r in active_requests if r.retention_type == retention_type])
        by_retention[retention_type] = count
    
    # Count scheduled deletions
    now = datetime.utcnow()
    next_7_days_threshold = now + timedelta(days=7)
    next_30_days_threshold = now + timedelta(days=30)
    
    scheduled_requests = [
        r for r in active_requests
        if r.deletion_scheduled_at is not None
        and r.auto_delete_enabled == 1
    ]
    
    next_7_days = len([
        r for r in scheduled_requests
        if now <= r.deletion_scheduled_at <= next_7_days_threshold
    ])
    
    next_30_days = len([
        r for r in scheduled_requests
        if now <= r.deletion_scheduled_at <= next_30_days_threshold
    ])
    
    total_scheduled = len(scheduled_requests)
    
    # Count protected items
    protected_items = len([r for r in active_requests if r.retention_type == 'forever'])
    
    return {
        "total_requests": total_requests,
        "by_retention_type": by_retention,
        "scheduled_deletions": {
            "next_7_days": next_7_days,
            "next_30_days": next_30_days,
            "total": total_scheduled
        },
        "protected_items": protected_items
    }
