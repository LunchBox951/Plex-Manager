"""
Torrent scoring engine for quality-based ranking and selection.
Implements resolution detection, seeder/size ratio scoring, season pack bonuses, and bandwidth penalties.
"""

import re
import json
from typing import List, Set, Optional, Dict
from dataclasses import dataclass

from src.prowlarr import TorrentResult
from src.qbittorrent import QBittorrentClient
from src.console import print_debug as debug, print_info as info, print_warning as warning, print_error as error

# Resolution multipliers for scoring
RESOLUTION_MULTIPLIERS = {
    '2160p': 4.0,  # 4K
    '1080p': 2,
    '720p': 1.0,
    '480p': 0.5,
}

# Patterns to detect and reject
BLOCKED_PATTERNS = [
    r'\bCAM\b', r'\bTS\b', r'\bHDCAM\b', r'\bTELECINE\b',
    r'\bSCREENER\b', r'\bHDTS\b', r'\bR5\b', r'\bR6\b'
]

# Season pack detection patterns
SEASON_PACK_PATTERNS = [
    r'S\d{2}(?!E\d)',  # S01, S02 (not followed by episode)
    r'Season\s*\d+',   # Season 1, Season 2
    r'\bComplete\b',   # Complete
    r'Full\s*Season',  # Full Season
    r'\d+x\d+-\d+x\d+', # 1x01-1x10
]

# Multi-season pack detection patterns (S01-S05, Seasons 1-5, Complete Series, etc.)
MULTI_SEASON_PATTERNS = [
    r'S(\d{2})-S(\d{2})',              # S01-S05, S01-S02
    r'S(\d{2})\s*-\s*S(\d{2})',        # S01 - S05
    r'Season[s]?\s*(\d+)\s*-\s*(\d+)', # Seasons 1-5, Season 1-5
    r'Complete\s*Series',              # Complete Series
    r'The\s*Complete',                 # The Complete (Collection)
    r'All\s*Seasons',                  # All Seasons
]

# Episode count detection patterns (for title parsing)
EPISODE_COUNT_PATTERNS = [
    r'(\d+)\s*Episodes?',  # "10 Episodes"
    r'(\d+)\s*Eps?',       # "10 Eps"
    r'E\d+-E(\d+)',        # "E01-E10"
    r'(\d+)x\d+',          # "1x10" (season x episodes)
]

# Minimum requirements
MIN_SEEDERS = 5
MIN_SIZE_MB = 100

# Dual audio detection patterns
DUAL_AUDIO_PATTERNS = [
    r'\bdual[\s\-_]*audio\b',
    r'\bmulti[\s\-_]*audio\b',
    r'\bmulti\b',  # "MULTi" is common
    r'eng\+jpn|jpn\+eng',
    r'\[dual[\s\-_]*audio\]',
    r'\(dual[\s\-_]*audio\)',
]


@dataclass
class ScoredTorrent:
    """Torrent with calculated score and metadata."""
    torrent: TorrentResult
    base_score: float
    final_score: float
    resolution: Optional[str]
    is_season_pack: bool
    episode_count: Optional[int]
    penalty_applied: Optional[float]
    reason: str


def extract_resolution(title: str) -> Optional[str]:
    """
    Extract resolution from torrent title.
    
    Args:
        title: Torrent title
        
    Returns:
        Resolution string (e.g., '1080p', '720p') or None
    """
    for resolution in RESOLUTION_MULTIPLIERS.keys():
        if resolution in title:
            return resolution
    
    # Check for 4K/UHD variants
    if re.search(r'\b(4K|UHD|2160)\b', title, re.IGNORECASE):
        return '2160p'
    
    return None


def has_dual_audio(title: str) -> bool:
    """
    Detect if torrent has dual audio (multiple language tracks).
    
    Common patterns: "Dual Audio", "Multi Audio", "ENG+JPN", etc.
    
    Args:
        title: Torrent title
        
    Returns:
        True if dual audio detected, False otherwise
    """
    title_lower = title.lower()
    for pattern in DUAL_AUDIO_PATTERNS:
        if re.search(pattern, title_lower):
            return True
    return False


def is_blocked_release(title: str) -> bool:
    """
    Check if torrent title matches blocked release patterns (CAM, TS, etc).
    
    Args:
        title: Torrent title
        
    Returns:
        True if blocked, False otherwise
    """
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            debug(f"[SCORING] Blocked release detected: {title} (pattern: {pattern})")
            return True
    return False


def detect_season_pack(title: str) -> bool:
    """
    Detect if torrent is a season pack (full or multi-episode).
    
    Args:
        title: Torrent title
        
    Returns:
        True if season pack detected, False otherwise
    """
    for pattern in SEASON_PACK_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            return True
    return False


def is_multi_season_pack(title: str) -> bool:
    """
    Detect if torrent contains multiple seasons (S01-S05, Complete Series, etc.).
    
    Args:
        title: Torrent title
        
    Returns:
        True if multi-season pack detected, False otherwise
        
    Examples:
        "Breaking Bad S01-S05 Complete" -> True
        "Breaking Bad Complete Series" -> True
        "Breaking Bad S01 Complete" -> False
        "Better Call Saul Seasons 1-3" -> True
    """
    for pattern in MULTI_SEASON_PATTERNS:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            # For patterns with capture groups, verify it's actually multiple seasons
            if match.groups():
                try:
                    season1 = int(match.group(1))
                    season2 = int(match.group(2))
                    if season2 > season1:  # Verify second season is greater
                        debug(f"[SCORING] Multi-season pack detected: {title} (S{season1:02d}-S{season2:02d})")
                        return True
                except (IndexError, ValueError):
                    # For "Complete Series", "All Seasons" patterns without groups
                    debug(f"[SCORING] Multi-season pack detected: {title}")
                    return True
            else:
                # Pattern matched without capture groups (Complete Series, All Seasons)
                debug(f"[SCORING] Multi-season pack detected: {title}")
                return True
    
    return False


def parse_episode_count_from_title(title: str) -> Optional[int]:
    """
    Parse episode count from torrent title (Tier 1 detection).
    
    Args:
        title: Torrent title
        
    Returns:
        Episode count if found, None otherwise
        
    Examples:
        "Show S01 10 Episodes" -> 10
        "Show 1x10" -> 10
        "Show E01-E10" -> 10
    """
    for pattern in EPISODE_COUNT_PATTERNS:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            try:
                count = int(match.group(1))
                debug(f"[SCORING] Parsed episode count from title: {count} (pattern: {pattern})")
                return count
            except (IndexError, ValueError):
                continue
    
    return None


def get_episode_count_from_tmdb(tmdb_id: int, season_number: int) -> Optional[int]:
    """
    Get episode count from TMDB cache (Tier 2 detection).
    
    Args:
        tmdb_id: TMDB ID
        season_number: Season number
        
    Returns:
        Episode count from cache or None if not cached
    """
    from src.pickle_stores import tmdb_season_cache_store
    
    # Build composite index key
    index_key = f"{tmdb_id}__{season_number}"
    cache_entry = tmdb_season_cache_store.find_by_index('tmdb_id__season_number', index_key)
    
    if cache_entry:
        debug(f"[SCORING] Found TMDB cache: {cache_entry.episode_count} episodes")
        return cache_entry.episode_count
    
    return None


def get_episode_count_from_magnet(magnet_link: str, qb_client: QBittorrentClient) -> Optional[int]:
    """
    Get episode count by analyzing magnet metadata (Tier 3 detection).
    
    This is the most accurate but expensive method - only use for top finalists.
    Temporarily adds magnet to qBittorrent to fetch file list, then removes it.
    
    Args:
        magnet_link: Magnet link
        qb_client: qBittorrent client instance
        
    Returns:
        Episode count based on video files, or None if failed
    """
    import time
    from src.torrent_validator import is_video_file, parse_episode_info
    
    try:
        # Extract info hash for tracking (supports magnet URIs and Prowlarr download URLs)
        info_hash = QBittorrentClient.resolve_info_hash(magnet_link)
        if not info_hash:
            warning("[SCORING] Could not extract info hash from magnet/URL")
            return None
        
        # Add torrent in paused state
        debug(f"[SCORING] Adding magnet temporarily for metadata: {info_hash[:8]}...")
        if not qb_client.add_magnet(magnet_link, paused=True):
            warning("[SCORING] Failed to add magnet to qBittorrent")
            return None
        
        # Wait for metadata to download
        time.sleep(3)
        
        # Get file list
        files = qb_client.get_torrent_files(info_hash)
        if not files:
            warning("[SCORING] No files found in torrent metadata")
            qb_client.delete_torrent(info_hash, delete_files=False)
            return None
        
        # Count unique episode numbers in video files
        episode_numbers = set()
        for file_info in files:
            filename = file_info.get('name', '')
            if is_video_file(filename):
                ep_info = parse_episode_info(filename)
                if ep_info and ep_info.get('episode'):
                    episode_numbers.add(ep_info['episode'])
        
        # Clean up - delete torrent
        qb_client.delete_torrent(info_hash, delete_files=False)
        
        count = len(episode_numbers) if episode_numbers else None
        debug(f"[SCORING] Detected {count} episodes from magnet metadata")
        return count
        
    except Exception as e:
        error(f"[SCORING] Failed to get episode count from magnet: {e}")
        return None


def get_episode_count(
    torrent: TorrentResult,
    tmdb_id: Optional[int] = None,
    season_number: Optional[int] = None,
    qb_client: Optional[QBittorrentClient] = None,
    use_magnet: bool = False
) -> Optional[int]:
    """
    Get episode count using 3-tier detection strategy.
    
    Tier 1: Parse title (fast, ~60% accurate)
    Tier 2: Query TMDB cache (fast, ~95% accurate)
    Tier 3: Analyze magnet metadata (slow, ~100% accurate, only for top 3)
    
    Args:
        torrent: Torrent result
        tmdb_id: TMDB ID for cache lookup
        season_number: Season number for cache lookup
        qb_client: qBittorrent client for metadata fetching
        use_magnet: Whether to use Tier 3 (expensive operation)
        
    Returns:
        Episode count or None if not detected
    """
    # Tier 1: Title parsing
    count = parse_episode_count_from_title(torrent.title)
    if count:
        debug(f"[SCORING] Episode count from title: {count}")
        return count
    
    # Tier 2: TMDB cache
    if tmdb_id and season_number:
        count = get_episode_count_from_tmdb(tmdb_id, season_number)
        if count:
            debug(f"[SCORING] Episode count from TMDB cache: {count}")
            return count
    
    # Tier 3: Magnet metadata (only if explicitly allowed)
    if use_magnet and qb_client:
        count = get_episode_count_from_magnet(torrent.magnet_link, qb_client)
        if count:
            debug(f"[SCORING] Episode count from magnet: {count}")
            return count
    
    debug("[SCORING] Could not determine episode count")
    return None


def calculate_base_score(torrent: TorrentResult, original_language: Optional[str] = None, relaxed: bool = False) -> float:
    """
    Calculate base torrent score using seeders/size ratio and resolution.

    Formula: (seeders / size_gb) × resolution_multiplier × dual_audio_multiplier

    Args:
        torrent: Torrent result
        original_language: Original language of the media (e.g., 'ja', 'ko', 'en')
        relaxed: If True, use relaxed thresholds (lower seeders, accept unknown resolution)

    Returns:
        Base score (0.0 if blocked/invalid)
    """
    # Block low-quality releases (always enforced, even in relaxed mode)
    if is_blocked_release(torrent.title):
        return 0.0

    # Minimum requirements (relaxed: seeders >= 2, size >= 50MB)
    min_seeders = 2 if relaxed else MIN_SEEDERS
    min_size_mb = 50 if relaxed else MIN_SIZE_MB

    if torrent.seeders < min_seeders:
        return 0.0

    if torrent.size_bytes < min_size_mb * 1024 * 1024:
        return 0.0

    # Calculate seeder/size ratio
    size_gb = max(torrent.size_gb, 0.1)  # Avoid division by zero
    base_score = torrent.seeders / size_gb

    # Apply resolution multiplier
    resolution = extract_resolution(torrent.title)
    if resolution:
        multiplier = RESOLUTION_MULTIPLIERS.get(resolution, 1.0)
        base_score *= multiplier
    else:
        # Unknown resolution - penalize (less harsh in relaxed mode)
        base_score *= 0.3 if relaxed else 0.1

    # Apply dual audio bonus for non-English content
    if original_language and original_language != 'en':
        if has_dual_audio(torrent.title):
            base_score *= 2.0

    return base_score


def apply_season_bonus(score: float, episode_count: int) -> float:
    """
    Apply season pack bonus by multiplying score by episode count.
    
    Example: 10-episode season pack = 10× higher score than single episode
    
    Args:
        score: Base score
        episode_count: Number of episodes in pack
        
    Returns:
        Score with season bonus applied
    """
    return score * episode_count


def apply_bandwidth_penalty(score: float, requested_episodes: int, total_episodes: int) -> float:
    """
    Apply quadratic bandwidth penalty for partial season requests.
    
    Formula: score × (requested / total)²
    
    Example: Requesting 5/10 episodes → score × 0.25
    
    Args:
        score: Base score
        requested_episodes: Number of episodes requested
        total_episodes: Total episodes in pack
        
    Returns:
        Score with penalty applied
    """
    if total_episodes == 0:
        return score
    
    ratio = requested_episodes / total_episodes
    penalty = ratio ** 2
    return score * penalty


def rank_torrents(
    torrents: List[TorrentResult],
    failed_hashes: Set[str],
    tmdb_id: Optional[int] = None,
    season_number: Optional[int] = None,
    requested_episodes: Optional[List[int]] = None,
    qb_client: Optional[QBittorrentClient] = None,
    original_language: Optional[str] = None
) -> List[ScoredTorrent]:
    """
    Rank torrents by score with bonuses/penalties applied.
    
    Args:
        torrents: List of torrent results from Prowlarr
        failed_hashes: Set of previously failed torrent hashes to exclude
        tmdb_id: TMDB ID for episode count lookup
        season_number: Season number for TV shows
        requested_episodes: Specific episodes requested (None = full season)
        qb_client: qBittorrent client for metadata fetching
        original_language: Original language of the media (for dual audio bonus)
        
    Returns:
        List of scored torrents sorted by final_score descending
    """
    scored_torrents = []
    
    for torrent in torrents:
        # Skip failed torrents
        if torrent.info_hash.lower() in failed_hashes:
            debug(f"[SCORING] Skipping failed torrent: {torrent.title}")
            continue
        
        # Calculate base score with dual audio bonus
        base_score = calculate_base_score(torrent, original_language)
        if base_score == 0.0:
            debug(f"[SCORING] Torrent filtered out (low score): {torrent.title}")
            continue
        
        final_score = base_score
        episode_count = None
        penalty_applied = None
        is_season_pack = detect_season_pack(torrent.title)
        resolution = extract_resolution(torrent.title)
        
        # Apply season pack bonus/penalty for TV shows
        if season_number is not None and is_season_pack:
            # Get episode count (Tier 1 + 2 only at this stage)
            episode_count = get_episode_count(
                torrent, tmdb_id, season_number, qb_client, use_magnet=False
            )
            
            if episode_count:
                # Apply season bonus
                final_score = apply_season_bonus(base_score, episode_count)
                
                # Apply bandwidth penalty if partial season requested
                if requested_episodes and len(requested_episodes) < episode_count:
                    penalty_ratio = len(requested_episodes) / episode_count
                    final_score = apply_bandwidth_penalty(final_score, len(requested_episodes), episode_count)
                    penalty_applied = penalty_ratio ** 2
        
        reason = f"{resolution or 'Unknown'} - {torrent.seeders} seeders"
        if is_season_pack and episode_count:
            reason += f" - {episode_count} episodes"
        if penalty_applied:
            reason += f" - {penalty_applied:.1%} bandwidth penalty"
        
        scored_torrents.append(ScoredTorrent(
            torrent=torrent,
            base_score=base_score,
            final_score=final_score,
            resolution=resolution,
            is_season_pack=is_season_pack,
            episode_count=episode_count,
            penalty_applied=penalty_applied,
            reason=reason
        ))
    
    # Fallback: if all torrents were filtered, retry with relaxed criteria
    if not scored_torrents and torrents:
        info(f"[SCORING] All {len(torrents)} torrents filtered, applying relaxed criteria")
        for torrent in torrents:
            if torrent.info_hash.lower() in failed_hashes:
                continue

            base_score = calculate_base_score(torrent, original_language, relaxed=True)
            if base_score == 0.0:
                continue

            final_score = base_score
            episode_count = None
            penalty_applied = None
            is_season_pack = detect_season_pack(torrent.title)
            resolution = extract_resolution(torrent.title)

            if season_number is not None and is_season_pack:
                episode_count = get_episode_count(
                    torrent, tmdb_id, season_number, qb_client, use_magnet=False
                )
                if episode_count:
                    final_score = apply_season_bonus(base_score, episode_count)
                    if requested_episodes and len(requested_episodes) < episode_count:
                        penalty_ratio = len(requested_episodes) / episode_count
                        final_score = apply_bandwidth_penalty(final_score, len(requested_episodes), episode_count)
                        penalty_applied = penalty_ratio ** 2

            reason = f"{resolution or 'Unknown'} - {torrent.seeders} seeders (relaxed)"
            if is_season_pack and episode_count:
                reason += f" - {episode_count} episodes"
            if penalty_applied:
                reason += f" - {penalty_applied:.1%} bandwidth penalty"

            scored_torrents.append(ScoredTorrent(
                torrent=torrent,
                base_score=base_score,
                final_score=final_score,
                resolution=resolution,
                is_season_pack=is_season_pack,
                episode_count=episode_count,
                penalty_applied=penalty_applied,
                reason=reason
            ))

    # When the caller requests a full season (season_number set, no episode
    # filter), drop single-episode torrents so they can't out-score a real pack
    # on seeders/size alone. Fall back to the unfiltered list only if there
    # are no season packs in the results at all.
    if season_number is not None and requested_episodes is None and scored_torrents:
        pack_only = [s for s in scored_torrents if s.is_season_pack]
        if pack_only:
            dropped = len(scored_torrents) - len(pack_only)
            info(f"[SCORING] Full-season requested: kept {len(pack_only)} season packs, dropped {dropped} non-pack torrents")
            scored_torrents = pack_only
        else:
            warning("[SCORING] Full-season requested but no season packs found — falling back to all results")

    # Sort by final score descending
    scored_torrents.sort(key=lambda x: x.final_score, reverse=True)

    # Refine top 3 with magnet metadata if needed
    if qb_client and season_number is not None:
        for i, scored in enumerate(scored_torrents[:3]):
            if scored.is_season_pack and not scored.episode_count:
                info(f"[SCORING] Refining top {i+1} torrent with magnet metadata...")
                episode_count = get_episode_count(
                    scored.torrent, tmdb_id, season_number, qb_client, use_magnet=True
                )
                
                if episode_count:
                    # Recalculate score with accurate episode count
                    scored.episode_count = episode_count
                    scored.final_score = apply_season_bonus(scored.base_score, episode_count)
                    
                    if requested_episodes and len(requested_episodes) < episode_count:
                        scored.final_score = apply_bandwidth_penalty(
                            scored.final_score, len(requested_episodes), episode_count
                        )
                        scored.penalty_applied = (len(requested_episodes) / episode_count) ** 2
                    
                    scored.reason = f"{scored.resolution or 'Unknown'} - {scored.torrent.seeders} seeders - {episode_count} episodes"
        
        # Re-sort after refinement
        scored_torrents.sort(key=lambda x: x.final_score, reverse=True)
    
    info(f"[SCORING] Ranked {len(scored_torrents)} torrents (filtered {len(torrents) - len(scored_torrents)})")
    return scored_torrents


def select_best_torrent(
    scored_torrents: List[ScoredTorrent],
    min_score: float = 1.0
) -> Optional[ScoredTorrent]:
    """
    Select the best torrent from scored list.
    
    Args:
        scored_torrents: List of scored torrents (should be pre-sorted)
        min_score: Minimum acceptable score
        
    Returns:
        Best torrent or None if no suitable torrent found
    """
    if not scored_torrents:
        return None
    
    best = scored_torrents[0]
    if best.final_score < min_score:
        warning(f"[SCORING] Best torrent score ({best.final_score:.2f}) below minimum ({min_score})")
        return None
    
    info(f"[SCORING] Selected torrent: {best.torrent.title} (score: {best.final_score:.2f})")
    return best
