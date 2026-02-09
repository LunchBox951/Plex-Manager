"""
Download monitoring service for qBittorrent integration.
Polls qBittorrent for status updates and handles file operations.
"""

import os
import json
import shutil
import tempfile
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from filelock import FileLock, Timeout

from src.database import SessionLocal
from src.models import Download, MediaRequest
from src.qbittorrent import get_qbittorrent_client
from src.torrent_validator import (
    is_video_file, is_subtitle_file, parse_episode_info,
    detect_subtitle_language, is_forced_subtitle,
    format_plex_subtitle_name, format_plex_episode_name
)

logger = logging.getLogger(__name__)


# Global scheduler instance
scheduler = None


def get_scheduler() -> AsyncIOScheduler:
    """Get or create global scheduler instance."""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
    return scheduler


def copy_file_safely(src: str, dst: str) -> bool:
    """
    Safely copy a file to destination, creating directories as needed.
    
    Args:
        src: Source file path
        dst: Destination file path
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create destination directory if needed
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        
        # Copy file
        shutil.copy2(src, dst)
        print(f"Copied: {src} -> {dst}")
        return True
        
    except Exception as e:
        print(f"Error copying file {src}: {e}")
        return False


def build_movie_path(title: str, year: Optional[int], filename: str) -> str:
    """
    Build Plex-compatible movie directory path.
    
    Args:
        title: Movie title
        year: Release year
        filename: Video filename
        
    Returns:
        Full path: /movies/Title (Year)/Title-Year.ext
    """
    movies_path = os.getenv('MOVIES_PATH')
    
    # Clean title for filesystem
    clean_title = title.strip()
    
    # Build directory name
    if year:
        dir_name = f"{clean_title} ({year})"
        base_name = f"{clean_title}-{year}"
    else:
        dir_name = clean_title
        base_name = clean_title
    
    # Get extension
    _, ext = os.path.splitext(filename)
    
    return os.path.join(movies_path, dir_name, f"{base_name}{ext}")


def build_tv_path(show_title: str, year: Optional[int], season: int, 
                  episode: int, episode_name: Optional[str], filename: str) -> str:
    """
    Build Plex-compatible TV show path.
    
    Args:
        show_title: TV show title
        year: Release year
        season: Season number
        episode: Episode number
        episode_name: Episode title (optional)
        filename: Original filename
        
    Returns:
        Full path: /tv/Show (Year)/Season N/S01E01 - Episode.ext
    """
    tv_path = os.getenv('TV_PATH')
    
    # Clean title
    clean_title = show_title.strip()
    
    # Build show directory name
    if year:
        show_dir = f"{clean_title} ({year})"
    else:
        show_dir = clean_title
    
    # Build season directory
    season_dir = f"Season {season}"
    
    # Get extension
    _, ext = os.path.splitext(filename)
    
    # Format episode filename
    episode_filename = format_plex_episode_name(show_title, season, episode, episode_name, ext)
    
    return os.path.join(tv_path, show_dir, season_dir, episode_filename)


def get_media_lock_path(tmdb_id: int, season: Optional[int] = None) -> str:
    """
    Get the lock file path for a specific media item.
    
    Args:
        tmdb_id: TMDB ID of the media
        season: Season number for TV shows (None for movies)
    
    Returns:
        Path to lock file
    """
    lock_dir = os.path.join(tempfile.gettempdir(), 'plex_manager_locks')
    os.makedirs(lock_dir, exist_ok=True)
    
    if season is not None:
        lock_name = f"plex_copy_{tmdb_id}_s{season}.lock"
    else:
        lock_name = f"plex_copy_{tmdb_id}.lock"
    
    return os.path.join(lock_dir, lock_name)


def process_movie_files(download: Download, torrent_files: List[Dict]) -> Dict[str, bool]:
    """
    Process and copy movie files to Plex directory with file locking.
    
    Args:
        download: Download record
        torrent_files: List of torrent files
        
    Returns:
        Dictionary mapping filenames to success status
    """
    # Acquire lock for this specific movie to prevent concurrent file operations
    lock_path = get_media_lock_path(download.tmdb_id)
    lock = FileLock(lock_path, timeout=300)  # 5 minute timeout
    
    try:
        with lock.acquire(timeout=300):
            logger.info(f"Acquired file lock for movie TMDB:{download.tmdb_id}")
            return _process_movie_files_locked(download, torrent_files)
    except Timeout:
        logger.error(f"Timeout acquiring file lock for movie TMDB:{download.tmdb_id}")
        return {}
    finally:
        # Clean up lock file if it exists
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except:
            pass


def _process_movie_files_locked(download: Download, torrent_files: List[Dict]) -> Dict[str, bool]:
    """
    Internal method - process and copy movie files (assumes lock is held).
    
    Args:
        download: Download record
        torrent_files: List of torrent files
        
    Returns:
        Dictionary mapping filenames to success status
    """
    results = {}
    
    # Parse metadata for movie title and year
    metadata = json.loads(download.metadata_json) if download.metadata_json else {}
    movie_name = metadata.get('name', 'Unknown Movie')
    
    # Try to extract year from name (e.g., "Movie Title (2019)")
    import re
    year_match = re.search(r'\((\d{4})\)', movie_name)
    year = int(year_match.group(1)) if year_match else None
    
    # Clean title (remove year from name)
    title = re.sub(r'\s*\(\d{4}\)', '', movie_name).strip()
    
    # Get download path from qBittorrent info
    download_base = download.download_path or os.getenv('DOWNLOADS_PATH')
    
    # Process each file
    video_copied = False
    for file_info in torrent_files:
        filename = file_info.get('name', '')
        file_path = os.path.join(download_base, filename)
        
        if not os.path.exists(file_path):
            continue
        
        if is_video_file(filename):
            # Copy main video file
            dest_path = build_movie_path(title, year, filename)
            success = copy_file_safely(file_path, dest_path)
            results[filename] = success
            if success:
                video_copied = True
                video_base_name = os.path.splitext(os.path.basename(dest_path))[0]
                
        elif is_subtitle_file(filename) and video_copied:
            # Copy subtitle with proper naming
            language = detect_subtitle_language(filename)
            forced = is_forced_subtitle(filename)
            _, ext = os.path.splitext(filename)
            
            subtitle_name = format_plex_subtitle_name(video_base_name, language, forced, ext)
            dest_dir = os.path.dirname(dest_path)
            subtitle_dest = os.path.join(dest_dir, subtitle_name)
            
            success = copy_file_safely(file_path, subtitle_dest)
            results[filename] = success
    
    return results


def process_tv_files(download: Download, torrent_files: List[Dict]) -> Dict[str, bool]:
    """
    Process and copy TV show files to Plex directory with file locking.
    
    Args:
        download: Download record
        torrent_files: List of torrent files
        
    Returns:
        Dictionary mapping filenames to success status
    """
    # Acquire lock for this specific season to prevent concurrent file operations
    lock_path = get_media_lock_path(download.tmdb_id, download.season)
    lock = FileLock(lock_path, timeout=300)  # 5 minute timeout
    
    try:
        with lock.acquire(timeout=300):
            logger.info(f"Acquired file lock for TV show TMDB:{download.tmdb_id} S{download.season}")
            return _process_tv_files_locked(download, torrent_files)
    except Timeout:
        logger.error(f"Timeout acquiring file lock for TV show TMDB:{download.tmdb_id} S{download.season}")
        return {}
    finally:
        # Clean up lock file if it exists
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except:
            pass


def _process_tv_files_locked(download: Download, torrent_files: List[Dict]) -> Dict[str, bool]:
    """
    Internal method - process and copy TV show files (assumes lock is held).
    
    Args:
        download: Download record
        torrent_files: List of torrent files
        
    Returns:
        Dictionary mapping filenames to success status
    """
    results = {}
    
    # Parse metadata for show title and year
    metadata = json.loads(download.metadata_json) if download.metadata_json else {}
    show_name = metadata.get('name', 'Unknown Show')
    
    # Try to extract year from name
    import re
    year_match = re.search(r'\((\d{4})\)', show_name)
    year = int(year_match.group(1)) if year_match else None
    
    # Clean title
    title = re.sub(r'\s*\(\d{4}\)', '', show_name).strip()
    
    # Get download path
    download_base = download.download_path or os.getenv('DOWNLOADS_PATH')
    
    # Track copied episodes for subtitle matching
    copied_episodes = {}  # filename -> dest_path
    
    # Process video files first
    for file_info in torrent_files:
        filename = file_info.get('name', '')
        file_path = os.path.join(download_base, filename)
        
        if not os.path.exists(file_path):
            continue
        
        if is_video_file(filename):
            # Parse episode info
            episode_info = parse_episode_info(filename)
            
            if episode_info:
                season = episode_info['season']
                episode = episode_info['episode']
                episode_name = episode_info.get('episode_name')
                
                # Build destination path
                dest_path = build_tv_path(title, year, season, episode, episode_name, filename)
                
                # Copy file
                success = copy_file_safely(file_path, dest_path)
                results[filename] = success
                
                if success:
                    copied_episodes[filename] = dest_path
            else:
                print(f"Could not parse episode info from: {filename}")
                results[filename] = False
    
    # Process subtitles
    for file_info in torrent_files:
        filename = file_info.get('name', '')
        file_path = os.path.join(download_base, filename)
        
        if not os.path.exists(file_path):
            continue
        
        if is_subtitle_file(filename):
            # Try to match subtitle to video file
            # Look for video with similar name
            base_name = os.path.splitext(filename)[0]
            
            matched = False
            for video_filename, video_dest in copied_episodes.items():
                video_base = os.path.splitext(video_filename)[0]
                
                # Check if subtitle matches video (same base name or similar)
                if base_name.startswith(video_base) or video_base.startswith(base_name):
                    # Copy subtitle next to video
                    language = detect_subtitle_language(filename)
                    forced = is_forced_subtitle(filename)
                    _, ext = os.path.splitext(filename)
                    
                    video_dir = os.path.dirname(video_dest)
                    video_base_name = os.path.splitext(os.path.basename(video_dest))[0]
                    
                    subtitle_name = format_plex_subtitle_name(video_base_name, language, forced, ext)
                    subtitle_dest = os.path.join(video_dir, subtitle_name)
                    
                    success = copy_file_safely(file_path, subtitle_dest)
                    results[filename] = success
                    matched = True
                    break
            
            if not matched:
                print(f"Could not match subtitle to episode: {filename}")
                results[filename] = False
    
    return results


def on_download_complete(download: Download, db_session):
    """
    Callback when download completes.
    Copies files to appropriate media directory.
    
    Args:
        download: Download record
        db_session: Database session
    """
    print(f"Processing completed download: {download.torrent_hash}")
    
    qb = get_qbittorrent_client()
    
    # Get torrent files
    torrent_files = qb.get_torrent_files(download.torrent_hash)
    
    if not torrent_files:
        print(f"No files found for torrent {download.torrent_hash}")
        download.status = "failed"
        download.failed_reason = "No files found in completed torrent"
        download.failed_at = datetime.utcnow()
        db_session.commit()
        return
    
    # Process based on media type
    if download.media_type == 'movie':
        results = process_movie_files(download, torrent_files)
    elif download.media_type == 'tv':
        results = process_tv_files(download, torrent_files)
    else:
        print(f"Unknown media type: {download.media_type}")
        download.status = "failed"
        download.failed_reason = f"Unknown media type: {download.media_type}"
        download.failed_at = datetime.utcnow()
        db_session.commit()
        return
    
    # Store processed files
    download.processed_files_json = json.dumps(results)
    
    # Check if any files failed
    failed_files = [f for f, success in results.items() if not success]
    
    if failed_files:
        if len(failed_files) == len(results):
            # All files failed
            download.status = "failed"
            download.failed_reason = "All files failed to copy"
            download.failed_at = datetime.utcnow()
        else:
            # Partial failure
            download.status = "partial_failed"
            download.failed_reason = f"{len(failed_files)} of {len(results)} files failed to copy"
            download.failed_at = datetime.utcnow()
    else:
        # All files succeeded
        download.status = "seeding"
        download.completed_at = datetime.utcnow()
    
    # Update MediaRequest status
    if download.media_request_id:
        media_request = db_session.query(MediaRequest).filter(
            MediaRequest.id == download.media_request_id
        ).first()
        
        if media_request:
            # Check all downloads for this request
            all_downloads = db_session.query(Download).filter(
                Download.media_request_id == media_request.id
            ).all()
            
            # Count download states
            downloading_count = sum(1 for d in all_downloads if d.status == 'downloading')
            seeding_count = sum(1 for d in all_downloads if d.status in ['seeding', 'completed'])
            failed_count = sum(1 for d in all_downloads if d.status in ['failed', 'partial_failed'])
            
            # Determine overall status
            if downloading_count > 0:
                # Still have active downloads - keep status as 'downloading'
                media_request.status = 'downloading'
            elif seeding_count == len(all_downloads):
                # All downloads complete and seeding
                media_request.status = 'available'
                media_request.completed_at = datetime.utcnow()
                
                # [PLACEHOLDER] Send completion notification
                print(f"[NOTIFICATION PLACEHOLDER] MediaRequest {media_request.id} ({media_request.title}) - Now available in Plex!")
                print(f"[NOTIFICATION PLACEHOLDER] Notify user_id {media_request.user_id}")
            elif seeding_count > 0:
                # Some completed, none downloading - set to processing while waiting for others
                media_request.status = 'processing'
            elif failed_count == len(all_downloads):
                # All failed
                media_request.status = 'failed'
                
                # [PLACEHOLDER] Send failure notification
                print(f"[NOTIFICATION PLACEHOLDER] MediaRequest {media_request.id} failed processing")
            else:
                # Mixed state - some failed but not all
                media_request.status = 'processing'
    
    db_session.commit()
    print(f"Download processing complete: {download.status}")


def on_seed_complete_or_timeout(download: Download, db_session, reason: str):
    """
    Callback when seeding is complete or timeout reached.
    Deletes download files and removes torrent from qBittorrent.
    
    Args:
        download: Download record
        db_session: Database session
        reason: 'seed_complete' or 'timeout'
    """
    print(f"Cleaning up download {download.torrent_hash}: {reason}")
    
    qb = get_qbittorrent_client()
    
    # Delete torrent and files from qBittorrent
    success = qb.delete_torrent(download.torrent_hash, delete_files=True)
    
    if success:
        # Mark as completed
        download.status = "completed"
        db_session.commit()
        print(f"Successfully cleaned up download {download.torrent_hash}")
    else:
        print(f"Failed to delete torrent from qBittorrent: {download.torrent_hash}")


def on_failure(download: Download, db_session, reason: str):
    """
    Callback when download fails.
    Marks as failed and removes from qBittorrent.
    
    Args:
        download: Download record
        db_session: Database session
        reason: Failure reason
    """
    print(f"[FAILURE] Download ID {download.id} | Hash: {download.torrent_hash} | Reason: {reason}")
    print(f"[FAILURE] Download ID {download.id} | Previous status: {download.status} | Setting to: failed")
    
    download.status = "failed"
    download.failed_reason = reason
    download.failed_at = datetime.utcnow()
    db_session.commit()
    
    print(f"[FAILURE] Download ID {download.id} | Attempting to remove from qBittorrent...")
    
    # Remove from qBittorrent
    try:
        qb = get_qbittorrent_client()
        if qb:
            qb.delete_torrent(download.torrent_hash, delete_files=True)
            print(f"[FAILURE] Download ID {download.id} | Successfully removed from qBittorrent")
        else:
            print(f"[FAILURE] Download ID {download.id} | Could not get qBittorrent client for cleanup")
    except Exception as e:
        print(f"[FAILURE] Download ID {download.id} | Error removing from qBittorrent: {e}")


def monitor_downloads():
    """
    Monitor active downloads and update status.
    Called by scheduler every 60 seconds.
    """
    db = SessionLocal()
    
    try:
        qb = get_qbittorrent_client()
        
        # Get all active downloads
        active_downloads = db.query(Download).filter(
            Download.status.in_(['pending', 'downloading', 'seeding'])
        ).all()
        
        if not active_downloads:
            return
        
        # Log summary of downloads being checked
        now = datetime.utcnow()
        print(f"\n[MONITOR] Checking {len(active_downloads)} active download(s)")
        for dl in active_downloads:
            age_seconds = (now - dl.added_at).total_seconds()
            age_minutes = age_seconds / 60
            print(f"[MONITOR]   ID {dl.id} | Hash: {dl.torrent_hash[:8]}... | Status: {dl.status} | Age: {age_minutes:.1f}min")
        
        for download in active_downloads:
            try:
                # Get current torrent info
                torrent_info = qb.get_torrent_info(download.torrent_hash)
                
                if not torrent_info:
                    # Grace period for new downloads - give them 10 minutes to connect
                    # Torrents need time to retrieve metadata and start downloading
                    download_age = datetime.utcnow() - download.added_at
                    grace_period_minutes = 10
                    grace_period_seconds = grace_period_minutes * 60
                    age_seconds = download_age.total_seconds()
                    remaining_seconds = grace_period_seconds - age_seconds
                    
                    if age_seconds < grace_period_seconds:
                        # Still within grace period - skip this check
                        print(f"[MONITOR] ID {download.id} | Not visible in qBittorrent yet | Age: {age_seconds:.0f}s | Grace remaining: {remaining_seconds:.0f}s ({remaining_seconds/60:.1f}min)")
                        continue
                    
                    # Grace period expired - mark as failed
                    print(f"[MONITOR] ID {download.id} | NOT FOUND in qBittorrent after grace period | Age: {age_seconds:.0f}s (>{grace_period_minutes}m) | Hash: {download.torrent_hash}")
                    print(f"[MONITOR] ID {download.id} | MARKING AS FAILED | Reason: Torrent not found in qBittorrent after grace period")
                    on_failure(download, db, "Torrent not found in qBittorrent after grace period")
                    continue
                
                # Torrent found in qBittorrent - update progress
                progress = torrent_info.get('progress', 0) * 100
                ratio = torrent_info.get('ratio', 0)
                state = torrent_info.get('state', 'unknown')
                
                print(f"[MONITOR] ID {download.id} | ✓ Found in qBittorrent | State: {state} | Progress: {progress:.1f}% | Ratio: {ratio:.2f}")
                
                download.progress = progress
                download.seed_ratio = ratio
                
                # Update MediaRequest status if linked
                if download.media_request_id:
                    media_request = db.query(MediaRequest).filter(
                        MediaRequest.id == download.media_request_id
                    ).first()
                    
                    if media_request and media_request.status == 'downloading':
                        # Keep status as downloading with updated progress tracked in Download records
                        pass
                
                qb_state = torrent_info.get('state', '')
                
                # Check for errors
                if 'error' in qb_state.lower() or qb_state == 'missingFiles':
                    print(f"[MONITOR] ID {download.id} | ERROR STATE DETECTED | qBittorrent state: {qb_state} | MARKING AS FAILED")
                    on_failure(download, db, f"qBittorrent error state: {qb_state}")
                    continue
                
                # Check if download just completed
                if download.status == 'downloading' and download.progress >= 99.9:
                    print(f"[MONITOR] ID {download.id} | DOWNLOAD COMPLETE | Progress: {download.progress:.1f}% | Transitioning to seeding")
                    on_download_complete(download, db)
                    continue
                
                # Check if seeding and ratio met
                if download.status == 'seeding':
                    if download.seed_ratio >= download.target_seed_ratio:
                        print(f"[MONITOR] ID {download.id} | SEED RATIO MET | Ratio: {download.seed_ratio:.2f} >= {download.target_seed_ratio:.2f} | Completing")
                        on_seed_complete_or_timeout(download, db, "seed_complete")
                        continue
                    
                    # Check for timeout
                    if download.will_timeout_at and datetime.utcnow() >= download.will_timeout_at:
                        print(f"[MONITOR] ID {download.id} | SEED TIMEOUT | Ratio: {download.seed_ratio:.2f}/{download.target_seed_ratio:.2f} | Timeout reached")
                        on_seed_complete_or_timeout(download, db, "timeout")
                        continue
                
                # Commit progress updates
                db.commit()
                
            except Exception as e:
                print(f"[MONITOR] ERROR processing download {download.id}: {e}")
                db.rollback()
        
        # Summary after checking all downloads
        final_status = db.query(Download).filter(
            Download.status.in_(['pending', 'downloading', 'seeding'])
        ).all()
        
        status_counts = {}
        for dl in final_status:
            status_counts[dl.status] = status_counts.get(dl.status, 0) + 1
        
        print(f"[MONITOR] Cycle complete | Active: {len(final_status)} | Breakdown: {status_counts}")
        
    except Exception as e:
        print(f"[MONITOR] FATAL ERROR in monitor_downloads: {e}")
    finally:
        db.close()


def cleanup_old_downloads():
    """
    Clean up old download records (>90 days).
    Called by scheduler daily.
    """
    db = SessionLocal()
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=90)
        
        # Delete completed downloads whose MediaRequest has been deleted
        deleted_completed = db.query(Download).join(
            MediaRequest, Download.media_request_id == MediaRequest.id
        ).filter(
            Download.status == 'completed',
            MediaRequest.status == 'deleted'
        ).delete(synchronize_session=False)
        
        # Delete failed downloads older than 90 days
        deleted_failed = db.query(Download).filter(
            Download.status.in_(['failed', 'partial_failed']),
            Download.failed_at < cutoff_date
        ).delete()
        
        db.commit()
        
        total_deleted = deleted_completed + deleted_failed
        if total_deleted > 0:
            print(f"Cleaned up {total_deleted} old download records ({deleted_completed} completed, {deleted_failed} failed)")
        
    except Exception as e:
        print(f"Error in cleanup_old_downloads: {e}")
        db.rollback()
    finally:
        db.close()


def verify_library_status():
    """
    Verify that 'available' media still exists in Plex library.
    Updates status to 'deleted' if media is missing.
    Called by scheduler daily.
    """
    from src.plex import check_media_exists
    
    db = SessionLocal()
    
    try:
        # Get all MediaRequests with status 'available'
        available_requests = db.query(MediaRequest).filter(
            MediaRequest.status == 'available'
        ).all()
        
        if not available_requests:
            print("No available media to verify")
            return
        
        print(f"Verifying library status for {len(available_requests)} media items...")
        
        verified_count = 0
        removed_count = 0
        error_count = 0
        
        for media_request in available_requests:
            try:
                # Check if media still exists in Plex
                exists = check_media_exists(
                    media_request.title,
                    media_request.year,
                    media_request.media_type
                )
                
                if exists.get('exists'):
                    # Media still in library - update verification timestamp
                    media_request.library_verified_at = datetime.utcnow()
                    verified_count += 1
                else:
                    # Media removed from library - mark as deleted
                    media_request.status = 'deleted'
                    media_request.deleted_at = datetime.utcnow()
                    media_request.library_removed_at = datetime.utcnow()
                    removed_count += 1
                    print(f"  Media removed from library: {media_request.title} ({media_request.year})")
                
            except Exception as e:
                error_count += 1
                print(f"  Error verifying {media_request.title}: {e}")
                continue
        
        db.commit()
        print(f"Library verification complete: {verified_count} verified, {removed_count} marked deleted, {error_count} errors")
        
    except Exception as e:
        print(f"Error in verify_library_status: {e}")
        db.rollback()
    finally:
        db.close()


def check_scheduled_deletions():
    """
    Check for scheduled media deletions based on retention policies.
    Runs daily at 4 AM to process media marked for deletion.
    """
    from src.retention import (
        get_effective_retention,
        send_deletion_notification,
        get_scheduled_deletions as get_scheduled,
        track_watch_status,
        track_episode_watch_status
    )
    from src.models import MediaRequest, EpisodeRetention
    from src.media import Movie, TVShow
    from src.plex import get_plex_server
    from datetime import datetime
    
    print(f"[{datetime.utcnow()}] Running scheduled deletion check...")
    db = get_database()
    
    try:
        plex = get_plex_server()
        deletion_count = 0
        
        # Get all media requests scheduled for deletion
        media_requests = db.query(MediaRequest).filter(
            MediaRequest.deletion_scheduled_at <= datetime.utcnow(),
            MediaRequest.auto_delete_enabled == 1,
            MediaRequest.status != 'deleted'
        ).all()
        
        print(f"Found {len(media_requests)} media items scheduled for deletion")
        
        for request in media_requests:
            try:
                # Verify effective retention still allows deletion
                effective_retention, protected = get_effective_retention(
                    db, request.tmdb_id, request.media_type
                )
                
                if protected or effective_retention == 'forever':
                    print(f"Skipping {request.title} - protected by retention policy")
                    request.deletion_scheduled_at = None
                    db.commit()
                    continue
                
                # Send notification placeholder
                send_deletion_notification(request)
                
                # Update watch status one last time before deletion
                track_watch_status(db, plex, request)
                
                # Delete media based on type
                if request.media_type == 'movie':
                    # Find movie in Plex
                    library = plex.library.section('Movies')
                    results = library.search(title=request.title, year=request.year)
                    
                    if results:
                        movie = Movie(results[0])
                        movie.delete()
                        request.status = 'deleted'
                        request.deleted_at = datetime.utcnow()
                        deletion_count += 1
                        print(f"Deleted movie: {request.title} (retention: {request.retention_type})")
                
                elif request.media_type == 'tv':
                    # Handle TV show episode deletions
                    episode_retentions = db.query(EpisodeRetention).filter(
                        EpisodeRetention.media_request_id == request.id,
                        EpisodeRetention.deletion_scheduled_at <= datetime.utcnow()
                    ).all()
                    
                    library = plex.library.section('TV Shows')
                    results = library.search(title=request.title)
                    
                    if results and episode_retentions:
                        show = results[0]
                        tv_show = TVShow(show)
                        
                        for ep_retention in episode_retentions:
                            # Check episode-level effective retention
                            ep_effective, ep_protected = get_effective_retention(
                                db, request.tmdb_id, 'tv',
                                ep_retention.season_number,
                                ep_retention.episode_number
                            )
                            
                            if ep_protected or ep_effective == 'forever':
                                print(f"Skipping S{ep_retention.season_number}E{ep_retention.episode_number} - protected")
                                ep_retention.deletion_scheduled_at = None
                                continue
                            
                            # Find and delete episode
                            for season in tv_show.seasons:
                                if season.season_number == ep_retention.season_number:
                                    for episode in season.episodes:
                                        if episode.episode_number == ep_retention.episode_number:
                                            episode.delete()
                                            deletion_count += 1
                                            print(f"Deleted {request.title} S{ep_retention.season_number}E{ep_retention.episode_number}")
                                            break
                        
                        # Check if all episodes deleted, mark show as deleted
                        remaining_episodes = db.query(EpisodeRetention).filter(
                            EpisodeRetention.media_request_id == request.id,
                            EpisodeRetention.deletion_scheduled_at.isnot(None)
                        ).count()
                        
                        if remaining_episodes == 0:
                            request.status = 'deleted'
                            request.deleted_at = datetime.utcnow()
                
                db.commit()
                
            except Exception as e:
                print(f"Error deleting {request.title}: {e}")
                db.rollback()
                continue
        
        print(f"Scheduled deletion check complete. Deleted {deletion_count} items.")
        
    except Exception as e:
        print(f"Error in check_scheduled_deletions: {e}")
        db.rollback()
    finally:
        db.close()


async def refresh_trending_cache():
    """Refresh trending cache data daily."""
    from src.TMDB import get_or_fetch_trending
    import logging
    
    logger = logging.getLogger(__name__)
    logger.info("Starting scheduled trending cache refresh")
    
    try:
        # Refresh trending movies
        await get_or_fetch_trending(media_type="movie", time_window="week", force_refresh=True)
        logger.info("Refreshed trending movies cache")
        
        # Refresh trending TV shows
        await get_or_fetch_trending(media_type="tv", time_window="week", force_refresh=True)
        logger.info("Refreshed trending TV cache")
        
    except Exception as e:
        logger.error(f"Error refreshing trending cache: {e}")


async def cleanup_expired_cache():
    """Remove expired images from cache."""
    import os
    import json
    from datetime import datetime, timezone
    import logging
    
    logger = logging.getLogger(__name__)
    logger.info("Starting scheduled cache cleanup")
    
    cache_dir = "cache/images/w500"
    metadata_file = "cache/image_metadata.json"
    
    if not os.path.exists(metadata_file):
        logger.warning("No image metadata file found")
        return
    
    try:
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        
        deleted_count = 0
        current_time = datetime.now(timezone.utc)
        
        for filename, file_info in list(metadata.items()):
            expires_at = datetime.fromisoformat(file_info['expires_at'])
            
            if current_time > expires_at:
                image_path = os.path.join(cache_dir, filename)
                if os.path.exists(image_path):
                    os.remove(image_path)
                    deleted_count += 1
                    logger.debug(f"Deleted expired image: {filename}")
                
                # Remove from metadata
                del metadata[filename]
        
        # Save updated metadata
        if deleted_count > 0:
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            logger.info(f"Cleaned up {deleted_count} expired images")
        else:
            logger.info("No expired images to clean up")
            
    except Exception as e:
        logger.error(f"Error cleaning up cache: {e}")


async def nightly_episode_check():
    """
    Nightly task running at 2 AM to:
    1. Retry failed/pending downloads (with retry_count < 5)
    2. Search for newly released episodes (aired yesterday) on tracked shows
    
    This consolidates retry logic and new episode detection in one job.
    """
    from src.models import TMDBSeasonCache, SeasonRequest
    from src.TMDB import season_service, safe_tmdb_call
    from src.prowlarr import get_prowlarr_client, CATEGORY_TV
    from src.scoring import rank_torrents, select_best_torrent
    from src.qbittorrent import get_qbittorrent_client, QBittorrentClient
    from src.torrent_validator import validate_torrent_files
    import time
    
    db = SessionLocal()
    logger.info("[NIGHTLY CHECK] Starting 2 AM episode check...")
    
    try:
        yesterday = (datetime.utcnow() - timedelta(days=1)).date()
        today = datetime.utcnow().date()
        
        # ====================================================================
        # Part 1: Retry Failed/Pending Downloads
        # ====================================================================
        
        logger.info("[NIGHTLY CHECK] Part 1: Retrying failed/pending downloads...")
        
        retry_downloads = db.query(Download).filter(
            Download.status.in_(['failed', 'pending']),
            Download.retry_count < 5
        ).all()
        
        logger.info(f"Found {len(retry_downloads)} downloads eligible for retry")
        
        for download in retry_downloads:
            try:
                # Get associated MediaRequest for title info
                media_request = db.query(MediaRequest).filter(
                    MediaRequest.id == download.media_request_id
                ).first()
                
                if not media_request:
                    logger.warning(f"Download {download.id} has no associated MediaRequest, skipping")
                    continue
                
                logger.info(f"Retrying download {download.id}: {media_request.title} (attempt {download.retry_count + 1}/5)")
                
                # Build search query
                if download.media_type == 'movie':
                    query = f"{media_request.title} {media_request.year}"
                    category = CATEGORY_TV  # Should be CATEGORY_MOVIES but using TV for now
                else:
                    if download.season and download.episodes:
                        # Individual episode(s)
                        episodes_list = json.loads(download.episodes)
                        if len(episodes_list) == 1:
                            query = f"{media_request.title} S{download.season:02d}E{episodes_list[0]:02d}"
                        else:
                            query = f"{media_request.title} S{download.season:02d}"
                    elif download.season:
                        # Full season
                        query = f"{media_request.title} S{download.season:02d}"
                    else:
                        # Entire show
                        query = media_request.title
                    
                    category = CATEGORY_TV
                
                # Search Prowlarr
                prowlarr = get_prowlarr_client()
                torrents = prowlarr.search(query, category)
                
                if not torrents:
                    logger.info(f"No torrents found for retry, incrementing retry count")
                    download.retry_count += 1
                    download.next_check_at = datetime.utcnow() + timedelta(days=1)
                    db.commit()
                    continue
                
                # Get failed hashes to exclude
                failed_hashes = {d.torrent_hash.lower() for d in db.query(Download).filter(
                    Download.status.in_(['failed', 'partial_failed'])
                ).all()}
                
                # Score torrents
                qb = get_qbittorrent_client()
                scored_torrents = rank_torrents(
                    torrents=torrents,
                    failed_hashes=failed_hashes,
                    tmdb_id=download.tmdb_id if download.media_type == 'tv' else None,
                    season_number=download.season,
                    requested_episodes=json.loads(download.episodes) if download.episodes else None,
                    db_session=db,
                    qb_client=qb
                )
                
                if not scored_torrents:
                    logger.info(f"No suitable torrents after filtering, incrementing retry count")
                    download.retry_count += 1
                    download.next_check_at = datetime.utcnow() + timedelta(days=1)
                    db.commit()
                    continue
                
                # Select best torrent
                best_torrent = select_best_torrent(scored_torrents)
                
                if not best_torrent:
                    logger.info(f"No torrents meet quality requirements, incrementing retry count")
                    download.retry_count += 1
                    download.next_check_at = datetime.utcnow() + timedelta(days=1)
                    db.commit()
                    continue
                
                # Extract info hash
                info_hash = QBittorrentClient.extract_info_hash(best_torrent.torrent.magnet_link)
                if not info_hash:
                    logger.error(f"Could not extract info hash from magnet")
                    download.retry_count += 1
                    db.commit()
                    continue
                
                # Check if already downloading
                existing = db.query(Download).filter(
                    Download.torrent_hash == info_hash,
                    Download.id != download.id
                ).first()
                
                if existing:
                    logger.info(f"Torrent already exists as download {existing.id}, marking original as failed")
                    download.status = 'failed'
                    download.failed_reason = f"Duplicate of download {existing.id}"
                    db.commit()
                    continue
                
                # Delete old torrent from qBittorrent if it exists
                if download.torrent_hash:
                    try:
                        qb.delete_torrent(download.torrent_hash, delete_files=True)
                        logger.info(f"Deleted old torrent {download.torrent_hash}")
                    except:
                        pass
                
                # Add new torrent to qBittorrent
                category = download.media_type
                save_path = os.getenv('DOWNLOADS_PATH', 'C:\\downloads')
                
                success = qb.add_magnet(
                    magnet_uri=best_torrent.torrent.magnet_link,
                    category=category,
                    save_path=save_path
                )
                
                if not success:
                    logger.error(f"qBittorrent failed to add magnet")
                    download.retry_count += 1
                    download.next_check_at = datetime.utcnow() + timedelta(days=1)
                    db.commit()
                    continue
                
                # Wait for metadata
                time.sleep(2)
                
                # Get torrent info
                torrent_info = qb.get_torrent_info(info_hash)
                if not torrent_info:
                    logger.error(f"Failed to retrieve torrent info")
                    qb.delete_torrent(info_hash, delete_files=True)
                    download.retry_count += 1
                    db.commit()
                    continue
                
                files = qb.get_torrent_files(info_hash)
                if not files:
                    logger.error(f"No files found in torrent")
                    qb.delete_torrent(info_hash, delete_files=True)
                    download.retry_count += 1
                    db.commit()
                    continue
                
                # Validate files
                validation = validate_torrent_files(files)
                if not validation.valid:
                    logger.error(f"Torrent validation failed: {validation.reason}")
                    qb.delete_torrent(info_hash, delete_files=True)
                    download.retry_count += 1
                    db.commit()
                    continue
                
                # Update download record with new torrent
                download.torrent_hash = info_hash
                download.magnet_link = best_torrent.torrent.magnet_link
                download.status = 'downloading'
                download.progress = 0.0
                download.retry_count += 1
                download.torrent_attempt = download.torrent_attempt + 1 if download.torrent_attempt else 2
                download.failed_reason = None
                download.failed_at = None
                download.metadata_json = json.dumps({
                    'name': torrent_info.get('name'),
                    'size': torrent_info.get('size'),
                    'num_files': len(files),
                    'indexer': best_torrent.torrent.indexer,
                    'score': best_torrent.final_score,
                    'retry': download.retry_count
                })
                
                db.commit()
                logger.info(f"✓ Successfully retried download {download.id} with new torrent")
                
            except Exception as e:
                logger.error(f"Error retrying download {download.id}: {e}")
                download.retry_count += 1
                download.next_check_at = datetime.utcnow() + timedelta(days=1)
                db.commit()
        
        # ====================================================================
        # Part 2: Check for New Episode Releases
        # ====================================================================
        
        logger.info("[NIGHTLY CHECK] Part 2: Checking for new episode releases...")
        
        # Get all tracked shows (track_upcoming = 1)
        tracked_requests = db.query(MediaRequest).filter(
            MediaRequest.media_type == 'tv',
            MediaRequest.track_upcoming == 1,
            MediaRequest.status != 'deleted'
        ).all()
        
        logger.info(f"Found {len(tracked_requests)} TV shows with upcoming episode tracking enabled")
        
        for media_request in tracked_requests:
            try:
                logger.info(f"Checking {media_request.title} for new episodes...")
                
                # Get ongoing seasons for this show
                ongoing_seasons = db.query(TMDBSeasonCache).filter(
                    TMDBSeasonCache.tmdb_id == media_request.tmdb_id,
                    TMDBSeasonCache.season_status == 'ongoing'
                ).all()
                
                if not ongoing_seasons:
                    logger.info(f"No ongoing seasons found for {media_request.title}")
                    continue
                
                for season_cache in ongoing_seasons:
                    logger.info(f"Checking Season {season_cache.season_number}...")
                    
                    # Fetch episode details from TMDB
                    season_details = safe_tmdb_call(
                        season_service.details,
                        media_request.tmdb_id,
                        season_cache.season_number
                    )
                    
                    if not season_details or not hasattr(season_details, 'episodes'):
                        logger.warning(f"Could not fetch season details")
                        continue
                    
                    # Check each episode
                    for episode in season_details.episodes:
                        if not hasattr(episode, 'air_date') or not episode.air_date:
                            continue
                        
                        try:
                            ep_air_date = datetime.strptime(episode.air_date, '%Y-%m-%d').date()
                        except:
                            continue
                        
                        # Check if episode aired yesterday
                        if ep_air_date != yesterday:
                            continue
                        
                        episode_num = episode.episode_number
                        logger.info(f"Found episode aired yesterday: S{season_cache.season_number:02d}E{episode_num:02d}")
                        
                        # Check if already requested (look for existing SeasonRequest)
                        existing_season_request = db.query(SeasonRequest).join(Download).filter(
                            Download.media_request_id == media_request.id,
                            SeasonRequest.season_number == season_cache.season_number,
                            SeasonRequest.episode_numbers.like(f'%{episode_num}%')
                        ).first()
                        
                        if existing_season_request:
                            logger.info(f"Episode already requested, skipping")
                            continue
                        
                        logger.info(f"Requesting new episode: {media_request.title} S{season_cache.season_number:02d}E{episode_num:02d}")
                        
                        try:
                            # Build search query
                            query = f"{media_request.title} S{season_cache.season_number:02d}E{episode_num:02d}"
                            
                            # Search Prowlarr
                            prowlarr = get_prowlarr_client()
                            torrents = prowlarr.search(query, CATEGORY_TV)
                            
                            if not torrents:
                                logger.info(f"No torrents found yet for this episode")
                                continue
                            
                            # Get failed hashes
                            failed_hashes = {d.torrent_hash.lower() for d in db.query(Download).filter(
                                Download.status.in_(['failed', 'partial_failed'])
                            ).all()}
                            
                            # Score torrents
                            qb = get_qbittorrent_client()
                            scored_torrents = rank_torrents(
                                torrents=torrents,
                                failed_hashes=failed_hashes,
                                tmdb_id=media_request.tmdb_id,
                                season_number=season_cache.season_number,
                                requested_episodes=[episode_num],
                                db_session=db,
                                qb_client=qb
                            )
                            
                            if not scored_torrents:
                                logger.info(f"No suitable torrents after filtering")
                                continue
                            
                            best_torrent = select_best_torrent(scored_torrents)
                            
                            if not best_torrent:
                                logger.info(f"No torrents meet quality requirements")
                                continue
                            
                            # Extract info hash
                            info_hash = QBittorrentClient.extract_info_hash(best_torrent.torrent.magnet_link)
                            if not info_hash:
                                logger.error(f"Could not extract info hash")
                                continue
                            
                            # Check for duplicates
                            existing_download = db.query(Download).filter(
                                Download.torrent_hash == info_hash
                            ).first()
                            
                            if existing_download:
                                logger.info(f"Torrent already downloading as {existing_download.id}")
                                continue
                            
                            # Add to qBittorrent
                            category = 'tv'
                            save_path = os.getenv('DOWNLOADS_PATH', 'C:\\downloads')
                            
                            success = qb.add_magnet(
                                magnet_uri=best_torrent.torrent.magnet_link,
                                category=category,
                                save_path=save_path
                            )
                            
                            if not success:
                                logger.error(f"qBittorrent failed to add magnet")
                                continue
                            
                            # Wait for metadata
                            time.sleep(2)
                            
                            # Get torrent info
                            torrent_info = qb.get_torrent_info(info_hash)
                            if not torrent_info:
                                logger.error(f"Failed to retrieve torrent info")
                                qb.delete_torrent(info_hash, delete_files=True)
                                continue
                            
                            files = qb.get_torrent_files(info_hash)
                            if not files:
                                logger.error(f"No files found in torrent")
                                qb.delete_torrent(info_hash, delete_files=True)
                                continue
                            
                            # Validate files
                            validation = validate_torrent_files(files)
                            if not validation.valid:
                                logger.error(f"Torrent validation failed: {validation.reason}")
                                qb.delete_torrent(info_hash, delete_files=True)
                                continue
                            
                            # Create Download record
                            timeout_date = datetime.utcnow() + timedelta(days=15)
                            
                            download = Download(
                                torrent_hash=info_hash,
                                magnet_link=best_torrent.torrent.magnet_link,
                                status='downloading',
                                media_type='tv',
                                metadata_json=json.dumps({
                                    'name': torrent_info.get('name'),
                                    'size': torrent_info.get('size'),
                                    'num_files': len(files),
                                    'indexer': best_torrent.torrent.indexer,
                                    'score': best_torrent.final_score,
                                    'auto_requested': True
                                }),
                                will_timeout_at=timeout_date,
                                tmdb_id=media_request.tmdb_id,
                                year=media_request.year,
                                season=season_cache.season_number,
                                episodes=json.dumps([episode_num]),
                                media_request_id=media_request.id,
                                retry_count=0,
                                torrent_attempt=1
                            )
                            
                            db.add(download)
                            db.flush()
                            
                            # Create SeasonRequest
                            season_req = SeasonRequest(
                                download_id=download.id,
                                season_number=season_cache.season_number,
                                episode_numbers=json.dumps([episode_num]),
                                status='pending'
                            )
                            
                            db.add(season_req)
                            db.commit()
                            
                            logger.info(f"✓ Successfully added download for S{season_cache.season_number:02d}E{episode_num:02d}")
                            
                        except Exception as ep_err:
                            logger.error(f"Error processing episode: {ep_err}")
                            continue
                
            except Exception as e:
                logger.error(f"Error checking {media_request.title}: {e}")
                continue
        
        logger.info("[NIGHTLY CHECK] Nightly episode check completed")
        
    except Exception as e:
        logger.error(f"[NIGHTLY CHECK] Fatal error in nightly episode check: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def start_monitor():
    """Start the download monitoring scheduler."""
    scheduler = get_scheduler()
    
    # Monitor downloads every 15 seconds for faster progress updates
    # max_instances=1 prevents overlapping executions if monitor takes >15s
    scheduler.add_job(
        monitor_downloads,
        'interval',
        seconds=15,
        id='monitor_downloads',
        replace_existing=True,
        max_instances=1
    )
    
    # Cleanup old downloads daily at 3 AM
    scheduler.add_job(
        cleanup_old_downloads,
        'cron',
        hour=3,
        minute=0,
        id='cleanup_downloads',
        replace_existing=True
    )
    
    # Verify library status daily at 1 AM
    scheduler.add_job(
        verify_library_status,
        'cron',
        hour=1,
        minute=0,
        id='verify_library',
        replace_existing=True
    )
    
    # Nightly episode check at 2 AM (retry failed + check new episodes)
    scheduler.add_job(
        nightly_episode_check,
        'cron',
        hour=2,
        minute=0,
        id='nightly_episodes',
        replace_existing=True
    )
    
    # Check scheduled deletions daily at 4 AM
    scheduler.add_job(
        check_scheduled_deletions,
        'cron',
        hour=4,
        minute=0,
        id='retention_deletions',
        replace_existing=True
    )
    
    # Refresh trending cache daily at 4 AM
    scheduler.add_job(
        refresh_trending_cache,
        'cron',
        hour=4,
        minute=0,
        id='refresh_trending',
        replace_existing=True
    )
    
    # Cleanup expired cache daily at 5 AM
    scheduler.add_job(
        cleanup_expired_cache,
        'cron',
        hour=5,
        minute=0,
        id='cleanup_cache',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Download monitor started - monitoring every 15 seconds")


def stop_monitor():
    """Stop the download monitoring scheduler."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown()
        print("Download monitor stopped")
