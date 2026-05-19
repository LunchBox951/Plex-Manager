"""
Download monitoring service for qBittorrent integration.
Polls qBittorrent for status updates and handles file operations.
"""

import os
import json
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from filelock import FileLock, Timeout

from src.database import SessionLocal
from src.pickle_models import Download, MediaRequest, EpisodeRetention, SeasonRequest
from src.pickle_stores import download_store, media_request_store, episode_retention_store, season_request_store, tmdb_season_cache_store
from src.qbittorrent import get_qbittorrent_client
from src.torrent_validator import (
    is_video_file, is_subtitle_file, parse_episode_info,
    detect_subtitle_language, is_forced_subtitle,
    format_plex_subtitle_name, format_plex_episode_name
)
from src.utils import normalize_title
from src.console import print_info, print_success, print_warning, print_error, print_debug, print_monitor, print_failure


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
        print_success(f"Copied: {src} -> {dst}")
        return True
        
    except Exception as e:
        print_error(f"Error copying file {src}: {e}")
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
    clean_title = normalize_title(title)
    
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
    clean_title = normalize_title(show_title)
    
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
            print_debug(f"Acquired file lock for movie TMDB:{download.tmdb_id}")
            return _process_movie_files_locked(download, torrent_files)
    except Timeout:
        print_error(f"Timeout acquiring file lock for movie TMDB:{download.tmdb_id}")
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
            print_debug(f"Acquired file lock for TV show TMDB:{download.tmdb_id} S{download.season}")
            return _process_tv_files_locked(download, torrent_files)
    except Timeout:
        print_error(f"Timeout acquiring file lock for TV show TMDB:{download.tmdb_id} S{download.season}")
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
                print_warning(f"Could not parse episode info from: {filename}")
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
                print_warning(f"Could not match subtitle to episode: {filename}")
                results[filename] = False
    
    return results


def on_download_complete(download: Download):
    """
    Callback when download completes.
    Copies files to appropriate media directory.
    
    Args:
        download: Download record
    """
    print_info(f"Processing completed download: {download.torrent_hash}", prefix="MONITOR")
    
    qb = get_qbittorrent_client()
    
    # Get torrent files
    torrent_files = qb.get_torrent_files(download.torrent_hash)
    
    if not torrent_files:
        print_error(f"No files found for torrent {download.torrent_hash}")
        download.status = "failed"
        download.failed_reason = "No files found in completed torrent"
        download.failed_at = datetime.utcnow()
        download_store.save(download)
        return
    
    # Process based on media type
    if download.media_type == 'movie':
        results = process_movie_files(download, torrent_files)
    elif download.media_type == 'tv':
        results = process_tv_files(download, torrent_files)
    else:
        print_error(f"Unknown media type: {download.media_type}")
        download.status = "failed"
        download.failed_reason = f"Unknown media type: {download.media_type}"
        download.failed_at = datetime.utcnow()
        download_store.save(download)
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
        media_request = media_request_store.load(str(download.media_request_id))
        
        if media_request:
            # Check all downloads for this request
            all_downloads = download_store.list_by_index('media_request_id', str(media_request.id))
            
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
                print_info(f"[NOTIFICATION PLACEHOLDER] MediaRequest {media_request.id} ({media_request.title}) - Now available in Plex!")
                print_info(f"[NOTIFICATION PLACEHOLDER] Notify user_id {media_request.user_id}")
            elif seeding_count > 0:
                # Some completed, none downloading - set to processing while waiting for others
                media_request.status = 'processing'
            elif failed_count == len(all_downloads):
                # All failed
                media_request.status = 'failed'
                
                # [PLACEHOLDER] Send failure notification
                print_info(f"[NOTIFICATION PLACEHOLDER] MediaRequest {media_request.id} failed processing")
            else:
                # Mixed state - some failed but not all
                media_request.status = 'processing'
            
            media_request_store.save(media_request)
    
    download_store.save(download)
    print_info(f"Download processing complete: {download.status}", prefix="MONITOR")


def on_seed_complete_or_timeout(download: Download, reason: str):
    """
    Callback when seeding is complete or timeout reached.
    Deletes download files and removes torrent from qBittorrent.
    
    Args:
        download: Download record
        reason: 'seed_complete' or 'timeout'
    """
    print_info(f"Cleaning up download {download.torrent_hash}: {reason}", prefix="MONITOR")
    
    qb = get_qbittorrent_client()
    
    # Delete torrent and files from qBittorrent
    success = qb.delete_torrent(download.torrent_hash, delete_files=True)
    
    if success:
        # Mark as completed
        download.status = "completed"
        download_store.save(download)
        print_success(f"Successfully cleaned up download {download.torrent_hash}")
    else:
        print_error(f"Failed to delete torrent from qBittorrent: {download.torrent_hash}")


def on_failure(download: Download, reason: str):
    """
    Callback when download fails.
    Marks as failed and removes from qBittorrent.
    
    Args:
        download: Download record
        reason: Failure reason
    """
    print_failure(f"Download ID {download.id} | Hash: {download.torrent_hash} | Reason: {reason}")
    print_failure(f"Download ID {download.id} | Previous status: {download.status} | Setting to: failed")
    
    download.status = "failed"
    download.failed_reason = reason
    download.failed_at = datetime.utcnow()
    download_store.save(download)
    
    print_info(f"Download ID {download.id} | Attempting to remove from qBittorrent...", prefix="MONITOR")
    
    # Remove from qBittorrent
    try:
        qb = get_qbittorrent_client()
        if qb:
            qb.delete_torrent(download.torrent_hash, delete_files=True)
            print_success(f"Download ID {download.id} | Successfully removed from qBittorrent")
        else:
            print_error(f"Download ID {download.id} | Could not get qBittorrent client for cleanup")
    except Exception as e:
        print_error(f"Download ID {download.id} | Error removing from qBittorrent: {e}")


def monitor_downloads():
    """
    Monitor active downloads and update status.
    Called by scheduler every 60 seconds.
    """
    db = SessionLocal()
    
    try:
        qb = get_qbittorrent_client()
        
        # Get all active downloads
        active_ids = download_store.get_ids_by_index_multi('status', ['pending', 'downloading', 'seeding'])
        active_downloads = [download_store.load(id) for id in active_ids if download_store.load(id)]
        
        if not active_downloads:
            return
        
        # Log summary of downloads being checked
        now = datetime.utcnow()
        print_monitor(f"Checking {len(active_downloads)} active download(s)", data={
            "active_downloads": len(active_downloads),
            "timestamp": now.isoformat()
        })
        for dl in active_downloads:
            age_seconds = (now - dl.added_at).total_seconds()
            age_minutes = age_seconds / 60
            print_info(f"  ID {dl.id} | Hash: {dl.torrent_hash[:8]}... | Status: {dl.status} | Age: {age_minutes:.1f}min", prefix="MONITOR")
        
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
                        print_monitor(f"ID {download.id} | Not visible in qBittorrent yet", data={
                            "download_id": download.id,
                            "age_seconds": int(age_seconds),
                            "grace_remaining_seconds": int(remaining_seconds),
                            "grace_remaining_minutes": round(remaining_seconds/60, 1)
                        })
                        continue
                    
                    # Grace period expired - mark as failed
                    print_monitor(f"ID {download.id} | NOT FOUND in qBittorrent after grace period", data={
                        "download_id": download.id,
                        "hash": download.torrent_hash,
                        "age_seconds": int(age_seconds),
                        "grace_period_minutes": grace_period_minutes,
                        "state_change": "marking_as_failed"
                    })
                    on_failure(download, "Torrent not found in qBittorrent after grace period")
                    continue
                
                # Torrent found in qBittorrent - update progress
                progress = torrent_info.get('progress', 0) * 100
                ratio = torrent_info.get('ratio', 0)
                state = torrent_info.get('state', 'unknown')
                
                print_monitor(f"ID {download.id} | ✓ Found in qBittorrent", data={
                    "download_id": download.id,
                    "state": state,
                    "progress": round(progress, 1),
                    "ratio": round(ratio, 2)
                })
                
                download.progress = progress
                download.seed_ratio = ratio
                
                # Update MediaRequest status if linked
                if download.media_request_id:
                    media_request = media_request_store.load(download.media_request_id)
                    
                    if media_request and media_request.status == 'downloading':
                        # Keep status as downloading with updated progress tracked in Download records
                        pass
                
                qb_state = torrent_info.get('state', '')
                
                # Check for errors
                if 'error' in qb_state.lower() or qb_state == 'missingFiles':
                    print_monitor(f"ID {download.id} | ERROR STATE DETECTED", data={
                        "download_id": download.id,
                        "qb_state": qb_state,
                        "state_change": "marking_as_failed"
                    })
                    on_failure(download, f"qBittorrent error state: {qb_state}")
                    continue
                
                # Check if download completed and files need to be copied
                # Handle both 'downloading' and 'seeding' states to catch completion
                if download.status in ['downloading', 'seeding']:
                    # Check for TRUE completion: 100% progress AND qBittorrent state indicates completion
                    # qBittorrent states that indicate download is complete and only uploading:
                    # - uploading: actively seeding
                    # - stalledUP: seeding but no peers requesting
                    # - pausedUP: paused while seeding
                    # - queuedUP: queued for seeding
                    # - checkingUP: checking files after completion
                    # - forcedUP: forced seeding
                    is_complete = (
                        download.progress >= 100.0 and
                        qb_state in ['uploading', 'stalledUP', 'pausedUP', 'queuedUP', 'checkingUP', 'forcedUP']
                    )
                    
                    # Check if files have been copied (indicated by processed_files_json being set)
                    files_already_copied = bool(download.processed_files_json)
                    
                    if is_complete and not files_already_copied:
                        print_monitor(f"ID {download.id} | DOWNLOAD COMPLETE - FILES READY FOR COPY", data={
                            "download_id": download.id,
                            "progress": round(download.progress, 1),
                            "qb_state": qb_state,
                            "state_change": "copying_files_to_library"
                        })
                        on_download_complete(download)
                        continue
                    elif is_complete and files_already_copied:
                        # Files already copied, ensure status is 'seeding'
                        if download.status != 'seeding':
                            download.status = 'seeding'
                            download_store.save(download)
                
                # Check if seeding and ratio met
                if download.status == 'seeding':
                    if download.seed_ratio >= download.target_seed_ratio:
                        print_monitor(f"ID {download.id} | SEED RATIO MET", data={
                            "download_id": download.id,
                            "current_ratio": round(download.seed_ratio, 2),
                            "target_ratio": round(download.target_seed_ratio, 2),
                            "state_change": "completing"
                        })
                        on_seed_complete_or_timeout(download, "seed_complete")
                        continue
                    
                    # Check for timeout
                    if download.will_timeout_at and datetime.utcnow() >= download.will_timeout_at:
                        print_monitor(f"ID {download.id} | SEED TIMEOUT", data={
                            "download_id": download.id,
                            "current_ratio": round(download.seed_ratio, 2),
                            "target_ratio": round(download.target_seed_ratio, 2),
                            "state_change": "timeout_reached"
                        })
                        on_seed_complete_or_timeout(download, "timeout")
                        continue
                
                # Save progress updates
                download_store.save(download)
                
            except Exception as e:
                print_error(f"ERROR processing download {download.id}: {e}", prefix="MONITOR")
        
        # Summary after checking all downloads
        active_ids = download_store.get_ids_by_index_multi('status', ['pending', 'downloading', 'seeding'])
        final_status = [download_store.load(id) for id in active_ids if download_store.load(id)]
        
        status_counts = {}
        for dl in final_status:
            status_counts[dl.status] = status_counts.get(dl.status, 0) + 1
        
        print_monitor("Cycle complete", data={
            "active_downloads": len(final_status),
            "status_breakdown": status_counts
        })
        
    except Exception as e:
        print_error(f"FATAL ERROR in monitor_downloads: {e}")
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
        deleted_completed = 0
        completed_ids = download_store.get_ids_by_index('status', 'completed')
        for id in completed_ids:
            download = download_store.load(id)
            if download and download.media_request_id:
                media_request = media_request_store.load(download.media_request_id)
                if media_request and media_request.status == 'deleted':
                    download_store.delete(id)
                    deleted_completed += 1
        
        # Delete failed downloads older than 90 days
        deleted_failed = 0
        failed_ids = download_store.get_ids_by_index_multi('status', ['failed', 'partial_failed'])
        for id in failed_ids:
            download = download_store.load(id)
            if download and download.failed_at and download.failed_at < cutoff_date:
                download_store.delete(id)
                deleted_failed += 1
        
        total_deleted = deleted_completed + deleted_failed
        if total_deleted > 0:
            print_info(f"Cleaned up {total_deleted} old download records ({deleted_completed} completed, {deleted_failed} failed)")
        
    except Exception as e:
        print_error(f"Error in cleanup_old_downloads: {e}")
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
        available_requests = media_request_store.list_by_index('status', 'available')
        
        if not available_requests:
            print_debug("No available media to verify")
            return
        
        print_info(f"Verifying library status for {len(available_requests)} media items...")
        
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
                    media_request_store.save(media_request)
                    verified_count += 1
                else:
                    # Media removed from library - mark as deleted
                    media_request.status = 'deleted'
                    media_request.deleted_at = datetime.utcnow()
                    media_request.library_removed_at = datetime.utcnow()
                    media_request_store.save(media_request)
                    removed_count += 1
                    print_warning(f"  Media removed from library: {media_request.title} ({media_request.year})")
                
            except Exception as e:
                error_count += 1
                print_error(f"  Error verifying {media_request.title}: {e}")
                continue
        
        print_info(f"Library verification complete: {verified_count} verified, {removed_count} marked deleted, {error_count} errors")
        
    except Exception as e:
        print_error(f"Error in verify_library_status: {e}")
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
    from src.media import Movie, TVShow
    from src.plex import get_plex_server
    from datetime import datetime
    
    print_info(f"[{datetime.utcnow()}] Running scheduled deletion check...")
    db = SessionLocal()
    
    try:
        plex = get_plex_server()
        deletion_count = 0
        
        # Get all media requests scheduled for deletion
        now = datetime.utcnow()
        all_requests = media_request_store.list_all()
        media_requests = [
            req for req in all_requests
            if req.deletion_scheduled_at and req.deletion_scheduled_at <= now
            and req.auto_delete_enabled == 1
            and req.status != 'deleted'
        ]
        
        print_info(f"Found {len(media_requests)} media items scheduled for deletion")
        
        for request in media_requests:
            try:
                # Verify effective retention still allows deletion
                effective_retention, protected = get_effective_retention(
                    db, request.tmdb_id, request.media_type
                )
                
                if protected or effective_retention == 'forever':
                    print_info(f"Skipping {request.title} - protected by retention policy")
                    request.deletion_scheduled_at = None
                    media_request_store.save(request)
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
                        media_request_store.save(request)
                        deletion_count += 1
                        print_success(f"Deleted movie: {request.title} (retention: {request.retention_type})")
                
                elif request.media_type == 'tv':
                    # Handle TV show episode deletions
                    all_ep_retentions = episode_retention_store.list_by_index('media_request_id', request.id)
                    now = datetime.utcnow()
                    episode_retentions = [
                        ep for ep in all_ep_retentions
                        if ep.deletion_scheduled_at and ep.deletion_scheduled_at <= now
                    ]
                    
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
                                print_info(f"Skipping S{ep_retention.season_number}E{ep_retention.episode_number} - protected")
                                ep_retention.deletion_scheduled_at = None
                                episode_retention_store.save(ep_retention)
                                continue
                            
                            # Find and delete episode
                            for season in tv_show.seasons:
                                if season.season_number == ep_retention.season_number:
                                    for episode in season.episodes:
                                        if episode.episode_number == ep_retention.episode_number:
                                            episode.delete()
                                            deletion_count += 1
                                            print_success(f"Deleted {request.title} S{ep_retention.season_number}E{ep_retention.episode_number}")
                                            break
                        
                        # Check if all episodes deleted, mark show as deleted
                        all_ep_retentions = episode_retention_store.list_by_index('media_request_id', request.id)
                        remaining_episodes = sum(
                            1 for ep in all_ep_retentions
                            if ep.deletion_scheduled_at is not None
                        )
                        
                        if remaining_episodes == 0:
                            request.status = 'deleted'
                            request.deleted_at = datetime.utcnow()
                            media_request_store.save(request)
                
            except Exception as e:
                print_error(f"Error deleting {request.title}: {e}")
                continue
        
        print_info(f"Scheduled deletion check complete. Deleted {deletion_count} items.")
        
    except Exception as e:
        print_error(f"Error in check_scheduled_deletions: {e}")
    finally:
        db.close()


async def refresh_trending_cache():
    """Refresh trending cache data daily."""
    from src.TMDB import get_or_fetch_trending
    
    print_info("Starting scheduled trending cache refresh")
    
    try:
        # Refresh trending movies
        await get_or_fetch_trending(media_type="movie", time_window="week", force_refresh=True)
        print_success("Refreshed trending movies cache")
        
        # Refresh trending TV shows
        await get_or_fetch_trending(media_type="tv", time_window="week", force_refresh=True)
        print_success("Refreshed trending TV cache")
        
    except Exception as e:
        print_error(f"Error refreshing trending cache: {e}")


async def cleanup_expired_cache():
    """Remove expired images from cache."""
    import os
    import json
    from datetime import datetime, timezone, timedelta
    
    print_info("Starting scheduled cache cleanup")
    
    cache_dir = "cache/images/w500"
    metadata_file = "cache/image_metadata.json"
    
    if not os.path.exists(metadata_file):
        print_warning("No image metadata file found")
        return
    
    try:
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        
        deleted_count = 0
        current_time = datetime.now(timezone.utc)
        
        for filename, file_info in list(metadata.items()):
            if 'expires_at' in file_info:
                expires_at = datetime.fromisoformat(file_info['expires_at'])
            elif 'downloaded_at' in file_info:
                expires_at = datetime.fromisoformat(file_info['downloaded_at']) + timedelta(days=7)
            else:
                continue

            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if current_time > expires_at:
                image_path = os.path.join(cache_dir, filename)
                if os.path.exists(image_path):
                    os.remove(image_path)
                    deleted_count += 1
                    print_debug(f"Deleted expired image: {filename}")
                
                # Remove from metadata
                del metadata[filename]
        
        # Save updated metadata
        if deleted_count > 0:
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            print_info(f"Cleaned up {deleted_count} expired images")
        else:
            print_debug("No expired images to clean up")
            
    except Exception as e:
        print_error(f"Error cleaning up cache: {e}")


async def _auto_request_season_pack(media_request, season_number: int) -> bool:
    """
    Auto-request a full-season download for a newly-discovered season.

    Mirrors the per-episode auto-request flow in nightly_episode_check but
    targets a full season pack (no episode filter).

    Returns True if a download was added, False otherwise.
    """
    from src.prowlarr import get_prowlarr_client, CATEGORY_TV
    from src.scoring import rank_torrents, select_best_torrent
    from src.qbittorrent import get_qbittorrent_client, QBittorrentClient
    from src.torrent_validator import validate_torrent_files
    import time

    query = f"{media_request.title} S{season_number:02d}"
    print_info(f"Searching for new season pack: {query}")

    prowlarr = get_prowlarr_client()
    torrents = prowlarr.search(query, CATEGORY_TV)
    if not torrents:
        print_info(f"No torrents found yet for {media_request.title} S{season_number:02d}")
        return False

    failed_ids = download_store.get_ids_by_index_multi('status', ['failed', 'partial_failed'])
    failed_downloads = [download_store.load(id) for id in failed_ids if download_store.load(id)]
    failed_hashes = {d.torrent_hash.lower() for d in failed_downloads}

    qb = get_qbittorrent_client()
    scored_torrents = rank_torrents(
        torrents=torrents,
        failed_hashes=failed_hashes,
        tmdb_id=media_request.tmdb_id,
        season_number=season_number,
        requested_episodes=None,
        qb_client=qb,
    )
    if not scored_torrents:
        print_info(f"No suitable season-pack torrents after filtering")
        return False

    best_torrent = select_best_torrent(scored_torrents)
    if not best_torrent:
        print_info(f"No season-pack torrents meet quality requirements")
        return False

    info_hash = QBittorrentClient.resolve_info_hash(best_torrent.torrent.magnet_link)
    if not info_hash:
        print_error(f"Could not extract info hash for season pack")
        return False

    existing_download = download_store.find_by_index('torrent_hash', info_hash)
    if existing_download:
        print_info(f"Season-pack torrent already exists as download {existing_download.id}")
        return False

    save_path = os.getenv('DOWNLOADS_PATH', 'C:\\downloads')
    if not qb.add_magnet(magnet_link=best_torrent.torrent.magnet_link, category='tv', save_path=save_path):
        print_error(f"qBittorrent rejected season-pack magnet")
        return False

    # Use the progressive-retry helper so larger season packs have time to
    # pull metadata (the previous 2 s sleep was too short and led to
    # "No files found in season-pack torrent" on a known-good pack).
    from src.downloads import await_torrent_connection
    connection_success, torrent_info, files = await await_torrent_connection(qb, info_hash)
    if not connection_success or not torrent_info or not files:
        print_error(f"Failed to fetch metadata for season-pack torrent after retries")
        qb.delete_torrent(info_hash, delete_files=True)
        return False

    validation = validate_torrent_files(files)
    if not validation.valid:
        print_error(f"Season-pack torrent validation failed: {validation.reason}")
        qb.delete_torrent(info_hash, delete_files=True)
        return False

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
            'auto_requested': True,
            'auto_reason': 'new_season_discovered',
        }),
        will_timeout_at=datetime.utcnow() + timedelta(days=15),
        tmdb_id=media_request.tmdb_id,
        year=media_request.year,
        season=season_number,
        episodes=None,
        media_request_id=media_request.id,
        retry_count=0,
        torrent_attempt=1,
    )
    download = download_store.save(download)

    season_req = SeasonRequest(
        download_id=download.id,
        season_number=season_number,
        episode_numbers=None,
        status='pending',
    )
    season_request_store.save(season_req)

    print_success(f"✓ Auto-requested new season pack: {media_request.title} S{season_number:02d}")
    return True


async def nightly_episode_check():
    """
    Nightly task running at 2 AM to:
    1. Retry failed/pending downloads (with retry_count < 5)
    2. Discover newly-added seasons on tracked shows and request season packs
    3. Search for newly released episodes (aired yesterday) on tracked shows

    This consolidates retry logic and new episode detection in one job.
    """
    from src.TMDB import season_service, safe_tmdb_call, get_tv_details
    from src.prowlarr import get_prowlarr_client, CATEGORY_TV, CATEGORY_MOVIES
    from src.scoring import rank_torrents, select_best_torrent
    from src.qbittorrent import get_qbittorrent_client, QBittorrentClient
    from src.torrent_validator import validate_torrent_files
    import time
    
    db = SessionLocal()
    print_info("Starting 2 AM episode check...", prefix="NIGHTLY CHECK")
    
    try:
        yesterday = (datetime.utcnow() - timedelta(days=1)).date()
        today = datetime.utcnow().date()
        
        # ====================================================================
        # Part 1: Retry Failed/Pending Downloads
        # ====================================================================
        
        print_info("Part 1: Retrying failed/pending downloads...", prefix="NIGHTLY CHECK")
        
        retry_ids = download_store.get_ids_by_index_multi('status', ['failed', 'pending'])
        retry_downloads = [
            download_store.load(id) for id in retry_ids
            if download_store.load(id) and download_store.load(id).retry_count < 5
        ]
        
        print_info(f"Found {len(retry_downloads)} downloads eligible for retry")
        
        for download in retry_downloads:
            try:
                # Get associated MediaRequest for title info
                media_request = media_request_store.load(download.media_request_id) if download.media_request_id else None
                
                if not media_request:
                    print_warning(f"Download {download.id} has no associated MediaRequest, skipping")
                    continue
                
                print_info(f"Retrying download {download.id}: {media_request.title} (attempt {download.retry_count + 1}/5)")
                
                # Build search query
                if download.media_type == 'movie':
                    query = f"{media_request.title} {media_request.year}"
                    category = CATEGORY_MOVIES
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
                    print_info(f"No torrents found for retry, incrementing retry count")
                    download.retry_count += 1
                    download.next_check_at = datetime.utcnow() + timedelta(days=1)
                    download_store.save(download)
                    continue
                
                # Get failed hashes to exclude
                failed_ids = download_store.get_ids_by_index_multi('status', ['failed', 'partial_failed'])
                failed_downloads = [download_store.load(id) for id in failed_ids if download_store.load(id)]
                failed_hashes = {d.torrent_hash.lower() for d in failed_downloads}
                
                # Score torrents
                qb = get_qbittorrent_client()
                scored_torrents = rank_torrents(
                    torrents=torrents,
                    failed_hashes=failed_hashes,
                    tmdb_id=download.tmdb_id,
                    season_number=download.season if download.media_type == 'tv' else None,
                    requested_episodes=json.loads(download.episodes) if download.media_type == 'tv' and download.episodes else None,
                    qb_client=qb
                )
                
                if not scored_torrents:
                    print_info(f"No suitable torrents after filtering, incrementing retry count")
                    download.retry_count += 1
                    download.next_check_at = datetime.utcnow() + timedelta(days=1)
                    download_store.save(download)
                    continue
                
                # Select best torrent
                best_torrent = select_best_torrent(scored_torrents)
                
                if not best_torrent:
                    print_info(f"No torrents meet quality requirements, incrementing retry count")
                    download.retry_count += 1
                    download.next_check_at = datetime.utcnow() + timedelta(days=1)
                    download_store.save(download)
                    continue
                
                # Extract info hash (supports magnet URIs and Prowlarr download URLs)
                info_hash = QBittorrentClient.resolve_info_hash(best_torrent.torrent.magnet_link)
                if not info_hash:
                    print_error(f"Could not extract info hash from magnet/URL")
                    download.retry_count += 1
                    download_store.save(download)
                    continue
                
                # Check if already downloading
                existing = download_store.find_by_index('torrent_hash', info_hash)
                
                if existing and existing.id != download.id:
                    print_info(f"Torrent already exists as download {existing.id}, marking original as failed")
                    download.status = 'failed'
                    download.failed_reason = f"Duplicate of download {existing.id}"
                    download_store.save(download)
                    continue
                
                # Delete old torrent from qBittorrent if it exists
                if download.torrent_hash:
                    try:
                        qb.delete_torrent(download.torrent_hash, delete_files=True)
                        print_info(f"Deleted old torrent {download.torrent_hash}")
                    except:
                        pass
                
                # Add new torrent to qBittorrent
                category = download.media_type
                save_path = os.getenv('DOWNLOADS_PATH', 'C:\\downloads')
                
                success = qb.add_magnet(
                    magnet_link=best_torrent.torrent.magnet_link,
                    category=category,
                    save_path=save_path
                )
                
                if not success:
                    print_error(f"qBittorrent failed to add magnet")
                    download.retry_count += 1
                    download.next_check_at = datetime.utcnow() + timedelta(days=1)
                    download_store.save(download)
                    continue
                
                # Wait for metadata
                time.sleep(2)
                
                # Get torrent info
                torrent_info = qb.get_torrent_info(info_hash)
                if not torrent_info:
                    print_error(f"Failed to retrieve torrent info")
                    qb.delete_torrent(info_hash, delete_files=True)
                    download.retry_count += 1
                    download_store.save(download)
                    continue
                
                files = qb.get_torrent_files(info_hash)
                if not files:
                    print_error(f"No files found in torrent")
                    qb.delete_torrent(info_hash, delete_files=True)
                    download.retry_count += 1
                    download_store.save(download)
                    continue
                
                # Validate files
                validation = validate_torrent_files(files)
                if not validation.valid:
                    print_error(f"Torrent validation failed: {validation.reason}")
                    qb.delete_torrent(info_hash, delete_files=True)
                    download.retry_count += 1
                    download_store.save(download)
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
                
                download_store.save(download)
                print_success(f"✓ Successfully retried download {download.id} with new torrent")
                
            except Exception as e:
                print_error(f"Error retrying download {download.id}: {e}")
                download.retry_count += 1
                download.next_check_at = datetime.utcnow() + timedelta(days=1)
                download_store.save(download)
        
        # ====================================================================
        # Part 2: Check for New Episode Releases
        # ====================================================================
        
        print_info("Part 2: Checking for new episode releases...", prefix="NIGHTLY CHECK")
        
        # Get all tracked shows (track_upcoming = 1)
        all_requests = media_request_store.list_all()
        tracked_requests = [
            req for req in all_requests
            if req.media_type == 'tv'
            and req.track_upcoming == 1
            and req.status != 'deleted'
        ]
        
        print_info(f"Found {len(tracked_requests)} TV shows with upcoming episode tracking enabled")
        
        for media_request in tracked_requests:
            try:
                print_info(f"Checking {media_request.title} for new episodes...")

                # Discover newly-added seasons from TMDB and request them.
                # Without this, shows requested before a later season existed never
                # pick up that season (e.g. Devil May Cry S02 after S01 was requested).
                try:
                    tv_details = get_tv_details(media_request.tmdb_id)
                except Exception as tmdb_err:
                    print_warning(f"Could not fetch TMDB details for {media_request.title}: {tmdb_err}")
                    tv_details = None

                if tv_details:
                    # Collect season numbers we've already requested for this show
                    existing_downloads = download_store.list_by_index('media_request_id', media_request.id)
                    requested_seasons = set()
                    for dl in existing_downloads:
                        if dl.season is not None:
                            requested_seasons.add(dl.season)
                        for sr in season_request_store.list_by_index('download_id', dl.id):
                            requested_seasons.add(sr.season_number)

                    for season_meta in tv_details.get('seasons', []) or []:
                        season_num = season_meta.get('season_number')
                        if season_num is None or season_num <= 0:
                            continue  # Skip specials (season 0) and malformed entries
                        if season_num in requested_seasons:
                            continue

                        air_date_str = season_meta.get('air_date')
                        if not air_date_str:
                            continue  # Future/unscheduled season
                        try:
                            season_air_date = datetime.strptime(air_date_str, '%Y-%m-%d').date()
                        except (ValueError, TypeError):
                            continue
                        if season_air_date > today:
                            continue  # Not yet aired

                        print_info(
                            f"Discovered new season for {media_request.title}: "
                            f"S{season_num:02d} (aired {season_air_date})"
                        )
                        try:
                            await _auto_request_season_pack(media_request, season_num)
                        except Exception as auto_err:
                            print_error(
                                f"Failed to auto-request {media_request.title} S{season_num:02d}: {auto_err}"
                            )

                # Get ongoing seasons for this show
                ongoing_seasons = [
                    s for s in tmdb_season_cache_store.list_by_index('tmdb_id', media_request.tmdb_id)
                    if s.season_status == 'ongoing'
                ]

                if not ongoing_seasons:
                    print_info(f"No ongoing seasons found for {media_request.title}")
                    continue
                
                for season_cache in ongoing_seasons:
                    print_info(f"Checking Season {season_cache.season_number}...")
                    
                    # Fetch episode details from TMDB
                    season_details = safe_tmdb_call(
                        season_service.details,
                        media_request.tmdb_id,
                        season_cache.season_number
                    )
                    
                    if not season_details or not hasattr(season_details, 'episodes'):
                        print_warning(f"Could not fetch season details")
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
                        print_info(f"Found episode aired yesterday: S{season_cache.season_number:02d}E{episode_num:02d}")
                        
                        # Check if already requested (look for existing SeasonRequest)
                        # Get all season requests for this media request
                        all_downloads = download_store.list_by_index('media_request_id', media_request.id)
                        existing_season_request = None
                        for dl in all_downloads:
                            season_reqs = season_request_store.list_by_index('download_id', dl.id)
                            for sr in season_reqs:
                                if sr.season_number == season_cache.season_number:
                                    if sr.episode_numbers and f'{episode_num}' in sr.episode_numbers:
                                        existing_season_request = sr
                                        break
                            if existing_season_request:
                                break
                        
                        if existing_season_request:
                            print_info(f"Episode already requested, skipping")
                            continue
                        
                        print_info(f"Requesting new episode: {media_request.title} S{season_cache.season_number:02d}E{episode_num:02d}")
                        
                        try:
                            # Build search query
                            query = f"{media_request.title} S{season_cache.season_number:02d}E{episode_num:02d}"
                            
                            # Search Prowlarr
                            prowlarr = get_prowlarr_client()
                            torrents = prowlarr.search(query, CATEGORY_TV)
                            
                            if not torrents:
                                print_info(f"No torrents found yet for this episode")
                                continue
                            
                            # Get failed hashes
                            failed_ids = download_store.get_ids_by_index_multi('status', ['failed', 'partial_failed'])
                            failed_downloads = [download_store.load(id) for id in failed_ids if download_store.load(id)]
                            failed_hashes = {d.torrent_hash.lower() for d in failed_downloads}
                            
                            # Score torrents
                            qb = get_qbittorrent_client()
                            scored_torrents = rank_torrents(
                                torrents=torrents,
                                failed_hashes=failed_hashes,
                                tmdb_id=media_request.tmdb_id,
                                season_number=season_cache.season_number,
                                requested_episodes=[episode_num],
                                qb_client=qb
                            )
                            
                            if not scored_torrents:
                                print_info(f"No suitable torrents after filtering")
                                continue
                            
                            best_torrent = select_best_torrent(scored_torrents)
                            
                            if not best_torrent:
                                print_info(f"No torrents meet quality requirements")
                                continue
                            
                            # Extract info hash (supports magnet URIs and Prowlarr download URLs)
                            info_hash = QBittorrentClient.resolve_info_hash(best_torrent.torrent.magnet_link)
                            if not info_hash:
                                print_error(f"Could not extract info hash")
                                continue
                            
                            # Check for duplicates
                            existing_download = download_store.find_by_index('torrent_hash', info_hash)
                            
                            if existing_download:
                                print_info(f"Torrent already downloading as {existing_download.id}")
                                continue
                            
                            # Add to qBittorrent
                            category = 'tv'
                            save_path = os.getenv('DOWNLOADS_PATH', 'C:\\downloads')
                            
                            success = qb.add_magnet(
                                magnet_link=best_torrent.torrent.magnet_link,
                                category=category,
                                save_path=save_path
                            )
                            
                            if not success:
                                print_error(f"qBittorrent failed to add magnet")
                                continue
                            
                            # Wait for metadata
                            time.sleep(2)
                            
                            # Get torrent info
                            torrent_info = qb.get_torrent_info(info_hash)
                            if not torrent_info:
                                print_error(f"Failed to retrieve torrent info")
                                qb.delete_torrent(info_hash, delete_files=True)
                                continue
                            
                            files = qb.get_torrent_files(info_hash)
                            if not files:
                                print_error(f"No files found in torrent")
                                qb.delete_torrent(info_hash, delete_files=True)
                                continue
                            
                            # Validate files
                            validation = validate_torrent_files(files)
                            if not validation.valid:
                                print_error(f"Torrent validation failed: {validation.reason}")
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
                            
                            download = download_store.save(download)
                            
                            # Create SeasonRequest
                            season_req = SeasonRequest(
                                download_id=download.id,
                                season_number=season_cache.season_number,
                                episode_numbers=json.dumps([episode_num]),
                                status='pending'
                            )
                            
                            season_request_store.save(season_req)
                            
                            print_success(f"✓ Successfully added download for S{season_cache.season_number:02d}E{episode_num:02d}")
                            
                        except Exception as ep_err:
                            print_error(f"Error processing episode: {ep_err}")
                            continue
                
            except Exception as e:
                print_error(f"Error checking {media_request.title}: {e}")
                continue
        
        print_info("Nightly episode check completed", prefix="NIGHTLY CHECK")
        
    except Exception as e:
        print_error(f"Fatal error in nightly episode check: {e}", prefix="NIGHTLY CHECK")
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
    print_success("Download monitor started - monitoring every 15 seconds")


def stop_monitor():
    """Stop the download monitoring scheduler."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown()
        print_info("Download monitor stopped")


