"""
Retention system for managing media deletion policies.
Handles watch tracking, deletion scheduling, and multi-user retention logic.
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from src.models import Settings
from src.pickle_models import MediaRequest, EpisodeRetention, Download
from src.pickle_stores import media_request_store, episode_retention_store, download_store
from src.plex import get_plex_server
from src.TMDB import get_tv_details, get_season_episode_count
from src.console import print_error


# Retention type hierarchy (most permissive to least permissive)
RETENTION_HIERARCHY = {
    'forever': 3,
    'watch_once': 2,
    'watch_as_released': 1
}


def get_setting(db: Session, key: str, default: str) -> str:
    """Get a setting value from the database."""
    setting = db.query(Settings).filter(Settings.key == key).first()
    return setting.value if setting else default


def get_grace_period_days(db: Session, retention_type: str) -> int:
    """Get the grace period in days for a retention type."""
    if retention_type == 'watch_once':
        return int(get_setting(db, 'watch_once_grace_days', '30'))
    elif retention_type == 'watch_as_released':
        return int(get_setting(db, 'watch_as_released_grace_days', '7'))
    else:  # forever
        return 0


def get_effective_retention(db: Optional[Session], tmdb_id: int, media_type: str, 
                           season: Optional[int] = None, 
                           episode: Optional[int] = None) -> Tuple[str, bool]:
    """
    Get the most permissive retention type across all users for a media item.
    Returns (retention_type, protected_from_deletion)
    """
    # Query all media requests for this TMDB ID
    index_key = f"{tmdb_id}__{media_type}"
    requests = [
        r for r in media_request_store.list_by_index('tmdb_id__media_type', index_key)
        if r.status != 'deleted'
    ]
    
    if not requests:
        return ('watch_once', False)
    
    # For TV shows with episode-specific overrides
    if media_type == 'tv' and season is not None and episode is not None:
        # Check all episode retention overrides for this episode
        episode_retentions = []
        for request in requests:
            all_ep_retentions = episode_retention_store.list_by_index('media_request_id', request.id)
            override = next(
                (ep for ep in all_ep_retentions 
                 if ep.season_number == season and ep.episode_number == episode),
                None
            )
            if override:
                episode_retentions.append(override.retention_type)
            else:
                # Use show-level retention if no override
                episode_retentions.append(request.retention_type)
        
        # Find most permissive retention
        most_permissive = max(episode_retentions, key=lambda x: RETENTION_HIERARCHY.get(x, 0))
        protected = most_permissive == 'forever'
        return (most_permissive, protected)
    
    # For movies or show-level TV retention
    retention_types = [req.retention_type for req in requests]
    most_permissive = max(retention_types, key=lambda x: RETENTION_HIERARCHY.get(x, 0))
    protected = most_permissive == 'forever'
    
    return (most_permissive, protected)


def track_watch_status(db: Optional[Session], plex_server, media_request: MediaRequest) -> bool:
    """
    Track watch status for a media request by querying Plex.
    Updates watched_at timestamp on first view.
    Returns True if watch status was updated.
    """
    try:
        if media_request.media_type == 'movie':
            # Search for movie in Plex
            library = plex_server.library.section('Movies')
            results = library.search(title=media_request.title, year=media_request.year)
            
            if results:
                movie = results[0]
                if hasattr(movie, 'lastViewedAt') and movie.lastViewedAt:
                    if not media_request.watched_at:
                        media_request.watched_at = movie.lastViewedAt
                        media_request_store.save(media_request)
                        return True
        
        elif media_request.media_type == 'tv':
            # Search for TV show in Plex
            library = plex_server.library.section('TV Shows')
            results = library.search(title=media_request.title)
            
            if results:
                show = results[0]
                # Check if any episode has been watched
                for episode in show.episodes():
                    if hasattr(episode, 'lastViewedAt') and episode.lastViewedAt:
                        if not media_request.watched_at:
                            media_request.watched_at = episode.lastViewedAt
                            media_request_store.save(media_request)
                            return True
                        break
        
        return False
        
    except Exception as e:
        print_error(f"Error tracking watch status for request {media_request.id}: {e}")
        return False


def track_episode_watch_status(db: Optional[Session], plex_server, episode_retention: EpisodeRetention) -> bool:
    """
    Track watch status for a specific episode.
    Updates watched_at timestamp on first view.
    Returns True if watch status was updated.
    """
    try:
        # Get the parent media request
        media_request = media_request_store.load(episode_retention.media_request_id)
        
        if not media_request:
            return False
        
        # Search for TV show in Plex
        library = plex_server.library.section('TV Shows')
        results = library.search(title=media_request.title)
        
        if results:
            show = results[0]
            # Find specific episode
            for episode in show.episodes():
                if (episode.seasonNumber == episode_retention.season_number and 
                    episode.episodeNumber == episode_retention.episode_number):
                    
                    if hasattr(episode, 'lastViewedAt') and episode.lastViewedAt:
                        if not episode_retention.watched_at:
                            episode_retention.watched_at = episode.lastViewedAt
                            episode_retention_store.save(episode_retention)
                            return True
                    break
        
        return False
        
    except Exception as e:
        print_error(f"Error tracking episode watch status for {episode_retention.id}: {e}")
        return False


def schedule_deletion(db: Optional[Session], media_request: MediaRequest) -> bool:
    """
    Schedule deletion for a media request based on retention policy.
    Returns True if deletion was scheduled.
    """
    # Check if already scheduled
    if media_request.deletion_scheduled_at:
        return False
    
    # Get effective retention across all users
    effective_retention, protected = get_effective_retention(
        None, media_request.tmdb_id, media_request.media_type
    )
    
    # Forever retention - never schedule deletion
    if effective_retention == 'forever' or protected:
        media_request.deletion_scheduled_at = None
        media_request_store.save(media_request)
        return False
    
    # Watch once - schedule after watch + grace period
    if effective_retention == 'watch_once':
        if media_request.watched_at:
            grace_days = get_grace_period_days(db, 'watch_once')
            media_request.deletion_scheduled_at = media_request.watched_at + timedelta(days=grace_days)
            media_request_store.save(media_request)
            return True
    
    # Watch as released (TV shows only) - handle at episode level
    elif effective_retention == 'watch_as_released' and media_request.media_type == 'tv':
        # Schedule at episode level, not show level
        return False
    
    return False


def schedule_episode_deletion(db: Optional[Session], media_request: MediaRequest, 
                              season: int, episode: int) -> bool:
    """
    Schedule deletion for a specific episode based on retention policy.
    For 'watch_as_released', checks if next episode has aired.
    Returns True if deletion was scheduled.
    """
    # Get or create episode retention record
    all_ep_retentions = episode_retention_store.list_by_index('media_request_id', media_request.id)
    episode_retention = next(
        (ep for ep in all_ep_retentions if ep.season_number == season and ep.episode_number == episode),
        None
    )
    
    # Get effective retention for this specific episode
    effective_retention, protected = get_effective_retention(
        None, media_request.tmdb_id, media_request.media_type, season, episode
    )
    
    # Forever retention - never schedule deletion
    if effective_retention == 'forever' or protected:
        if episode_retention:
            episode_retention.deletion_scheduled_at = None
            episode_retention_store.save(episode_retention)
        return False
    
    # Create episode retention if it doesn't exist (inherit from show)
    if not episode_retention:
        episode_retention = EpisodeRetention(
            media_request_id=media_request.id,
            season_number=season,
            episode_number=episode,
            retention_type=media_request.retention_type
        )
        episode_retention = episode_retention_store.save(episode_retention)
    
    # Already scheduled
    if episode_retention.deletion_scheduled_at:
        return False
    
    # Not watched yet
    if not episode_retention.watched_at:
        return False
    
    grace_days = get_grace_period_days(db, effective_retention)
    
    # Watch once - schedule after watch + grace period
    if effective_retention == 'watch_once':
        episode_retention.deletion_scheduled_at = episode_retention.watched_at + timedelta(days=grace_days)
        episode_retention_store.save(episode_retention)
        return True
    
    # Watch as released - check if next episode is available
    elif effective_retention == 'watch_as_released':
        try:
            # TODO: Implement get_season_details in TMDB.py for episode air date checking
            # For now, skip this check - requires TMDB season details API
            return False
            # Check if next episode exists and has aired
            # season_info = get_season_details(media_request.tmdb_id, season)
            
            # Check if there's a next episode in this season
            if episode < len(season_info.get('episodes', [])):
                next_episode_info = season_info['episodes'][episode]  # 0-indexed
                air_date_str = next_episode_info.get('air_date')
                
                if air_date_str:
                    air_date = datetime.strptime(air_date_str, '%Y-%m-%d').date()
                    if air_date <= datetime.now().date():
                        # Next episode has aired, schedule deletion
                        episode_retention.deletion_scheduled_at = episode_retention.watched_at + timedelta(days=grace_days)
                        episode_retention_store.save(episode_retention)
                        return True
            else:
                # Last episode of season - check if there's a next season
                show_info = get_tv_details(media_request.tmdb_id)
                number_of_seasons = show_info.get('number_of_seasons', 0)
                
                if season >= number_of_seasons:
                    # Series ended, schedule deletion
                    episode_retention.deletion_scheduled_at = episode_retention.watched_at + timedelta(days=grace_days)
                    episode_retention_store.save(episode_retention)
                    return True
        except Exception as e:
            print_error(f"Error checking next episode for scheduling: {e}")
    
    return False


def recalculate_deletion_schedule(db: Optional[Session], media_request: MediaRequest) -> None:
    """
    Recalculate deletion schedule after retention type change.
    Uses current watched_at + new grace period.
    """
    # Get effective retention
    effective_retention, protected = get_effective_retention(
        None, media_request.tmdb_id, media_request.media_type
    )
    
    # Forever - clear schedule
    if effective_retention == 'forever' or protected:
        media_request.deletion_scheduled_at = None
        media_request_store.save(media_request)
        
        # Update associated download
        downloads = download_store.list_by_index('media_request_id', media_request.id)
        for download in downloads:
            download.protected_from_deletion = 1
            download.retention_type = 'forever'
            download_store.save(download)
        
        return
    
    # Recalculate based on new retention type
    if media_request.watched_at:
        grace_days = get_grace_period_days(db, effective_retention)
        new_schedule = media_request.watched_at + timedelta(days=grace_days)
        media_request.deletion_scheduled_at = new_schedule
        media_request_store.save(media_request)
        
        # Update download retention type
        downloads = download_store.list_by_index('media_request_id', media_request.id)
        for download in downloads:
            download.retention_type = effective_retention
            download.protected_from_deletion = 0
            download_store.save(download)
    else:
        # Not watched yet - clear schedule
        media_request.deletion_scheduled_at = None
        media_request_store.save(media_request)


def get_scheduled_deletions(db: Optional[Session], user_id: Optional[int] = None, 
                           media_type: Optional[str] = None,
                           limit: int = 100, offset: int = 0) -> List[Dict]:
    """
    Get scheduled deletions with optional filters.
    Returns list of dictionaries with deletion details.
    """
    # Get all media requests
    all_requests = media_request_store.list()
    
    # Filter for scheduled deletions
    requests = [
        req for req in all_requests
        if req.deletion_scheduled_at is not None
        and req.auto_delete_enabled == 1
        and req.status != 'deleted'
    ]
    
    # Apply user_id filter
    if user_id:
        requests = [req for req in requests if req.user_id == user_id]
    
    # Apply media_type filter
    if media_type:
        requests = [req for req in requests if req.media_type == media_type]
    
    # Sort by deletion_scheduled_at
    requests.sort(key=lambda x: x.deletion_scheduled_at)
    
    # Apply pagination
    requests = requests[offset:offset + limit]
    
    results = []
    for request in requests:
        # Get effective retention
        effective_retention, _ = get_effective_retention(
            None, request.tmdb_id, request.media_type
        )
        
        results.append({
            'id': request.id,
            'user_id': request.user_id,
            'tmdb_id': request.tmdb_id,
            'media_type': request.media_type,
            'title': request.title,
            'year': request.year,
            'retention_type': request.retention_type,
            'effective_retention': effective_retention,
            'watched_at': request.watched_at.isoformat() if request.watched_at else None,
            'deletion_scheduled_at': request.deletion_scheduled_at.isoformat() if request.deletion_scheduled_at else None,
            'days_until_deletion': (request.deletion_scheduled_at - datetime.utcnow()).days if request.deletion_scheduled_at else None
        })
    
    return results


def get_scheduled_episode_deletions(db: Optional[Session], media_request_id: int) -> List[Dict]:
    """Get scheduled episode deletions for a TV show request."""
    # Get episodes for this media request
    episodes = episode_retention_store.list_by_index('media_request_id', str(media_request_id))
    
    # Filter for scheduled deletions
    episodes = [
        ep for ep in episodes
        if ep.deletion_scheduled_at is not None
    ]
    
    # Sort by season and episode number
    episodes.sort(key=lambda x: (x.season_number, x.episode_number))
    
    return [
        {
            'id': ep.id,
            'season': ep.season_number,
            'episode': ep.episode_number,
            'retention_type': ep.retention_type,
            'watched_at': ep.watched_at.isoformat() if ep.watched_at else None,
            'deletion_scheduled_at': ep.deletion_scheduled_at.isoformat() if ep.deletion_scheduled_at else None,
            'days_until_deletion': (ep.deletion_scheduled_at - datetime.utcnow()).days if ep.deletion_scheduled_at else None
        }
        for ep in episodes
    ]


def cancel_scheduled_deletion(db: Optional[Session], media_request_id: int) -> bool:
    """Cancel a scheduled deletion by disabling auto-delete."""
    media_request = media_request_store.load(str(media_request_id))
    
    if media_request:
        media_request.auto_delete_enabled = 0
        media_request_store.save(media_request)
        return True
    
    return False


# Placeholder for future notification system
def schedule_deletion_notification(media_request: MediaRequest, days_before: int = 1):
    """
    Placeholder for scheduling deletion notifications.
    TODO: Implement email/webhook notifications in future phase.
    """
    print(f"[NOTIFICATION PLACEHOLDER] Would notify user {media_request.user_id} about "
          f"{media_request.title} deletion in {days_before} days")


def send_deletion_notification(media_request: MediaRequest):
    """
    Placeholder for sending deletion notification.
    TODO: Implement email/webhook notifications in future phase.
    """
    print(f"[NOTIFICATION PLACEHOLDER] Would notify user {media_request.user_id} that "
          f"{media_request.title} is being deleted")
