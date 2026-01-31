"""
Torrent file validation and parsing utilities.
Validates file types, extracts episode information, and detects subtitle languages.
"""

import re
import os
from typing import Dict, List, Optional, Tuple, Any


# File type allowlists
VIDEO_EXTENSIONS = {
    '.mkv', '.mp4', '.avi', '.mov', '.webm', '.m4v', '.flv',
    '.wmv', '.mpg', '.mpeg', '.m2ts', '.ts'
}

SUBTITLE_EXTENSIONS = {
    '.srt', '.ass', '.sub', '.vtt', '.ssa'
}

# Dangerous file extensions blocklist
DANGEROUS_EXTENSIONS = {
    '.exe', '.bat', '.sh', '.py', '.dll', '.msi', '.app',
    '.deb', '.rpm', '.jar', '.cmd', '.ps1', '.vbs', '.scr',
    '.com', '.pif', '.apk', '.dmg', '.run', '.bin'
}


class ValidationResult:
    """Result of file validation."""
    
    def __init__(self, valid: bool, reason: str = "", valid_files: Optional[List[str]] = None,
                 invalid_files: Optional[List[str]] = None):
        self.valid = valid
        self.reason = reason
        self.valid_files = valid_files or []
        self.invalid_files = invalid_files or []
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "valid": self.valid,
            "reason": self.reason,
            "valid_files": self.valid_files,
            "invalid_files": self.invalid_files
        }


def get_file_extension(filename: str) -> str:
    """
    Get lowercase file extension.
    
    Args:
        filename: File name or path
        
    Returns:
        Lowercase extension including dot (e.g., '.mkv')
    """
    _, ext = os.path.splitext(filename)
    return ext.lower()


def is_video_file(filename: str) -> bool:
    """Check if file is a video file."""
    return get_file_extension(filename) in VIDEO_EXTENSIONS


def is_subtitle_file(filename: str) -> bool:
    """Check if file is a subtitle file."""
    return get_file_extension(filename) in SUBTITLE_EXTENSIONS


def is_dangerous_file(filename: str) -> bool:
    """Check if file has a dangerous extension."""
    return get_file_extension(filename) in DANGEROUS_EXTENSIONS


def validate_torrent_files(files: List[Dict]) -> ValidationResult:
    """
    Validate torrent files for safety and acceptable types.
    
    Args:
        files: List of file dictionaries with 'name' key
        
    Returns:
        ValidationResult with validation status and details
    """
    valid_files = []
    invalid_files = []
    dangerous_files = []
    
    for file_info in files:
        filename = file_info.get('name', '')
        
        # Check for dangerous files first
        if is_dangerous_file(filename):
            dangerous_files.append(filename)
            invalid_files.append(filename)
            continue
        
        # Check if it's a video or subtitle file
        if is_video_file(filename) or is_subtitle_file(filename):
            valid_files.append(filename)
        else:
            # Other files (like .nfo, .txt) are allowed but not tracked
            continue
    
    # Validation fails if any dangerous files found
    if dangerous_files:
        return ValidationResult(
            valid=False,
            reason=f"Dangerous file types detected: {', '.join(dangerous_files[:3])}",
            valid_files=valid_files,
            invalid_files=invalid_files
        )
    
    # Validation fails if no video files found
    video_files = [f for f in valid_files if is_video_file(f)]
    if not video_files:
        return ValidationResult(
            valid=False,
            reason="No video files found in torrent",
            valid_files=valid_files,
            invalid_files=invalid_files
        )
    
    return ValidationResult(
        valid=True,
        reason="All files validated successfully",
        valid_files=valid_files,
        invalid_files=invalid_files
    )


def extract_episode_info(filename: str) -> Optional[Dict[str, Any]]:
    """
    Extract episode information from filename using common patterns.
    
    Args:
        filename: Video filename
        
    Returns:
        Dictionary with season, episode, and optionally episode name
    """
    # Pattern 1: S01E01 or S1E1 format
    pattern1 = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,2})', re.IGNORECASE)
    match = pattern1.search(filename)
    if match:
        season = int(match.group(1))
        episode = int(match.group(2))
        
        # Try to extract episode name (text after episode number before extension)
        name_pattern = re.compile(
            rf'{match.group(0)}\s*-?\s*([^/\\\.]+)',
            re.IGNORECASE
        )
        name_match = name_pattern.search(filename)
        episode_name = name_match.group(1).strip() if name_match else None
        
        return {
            "season": season,
            "episode": episode,
            "episode_name": episode_name
        }
    
    # Pattern 2: 1x01 format
    pattern2 = re.compile(r'(\d{1,2})x(\d{1,2})', re.IGNORECASE)
    match = pattern2.search(filename)
    if match:
        season = int(match.group(1))
        episode = int(match.group(2))
        
        # Try to extract episode name
        name_pattern = re.compile(
            rf'{match.group(0)}\s*-?\s*([^/\\\.]+)',
            re.IGNORECASE
        )
        name_match = name_pattern.search(filename)
        episode_name = name_match.group(1).strip() if name_match else None
        
        return {
            "season": season,
            "episode": episode,
            "episode_name": episode_name
        }
    
    # Pattern 3: Episode XX format
    pattern3 = re.compile(r'[Ee]pisode\s+(\d{1,2})', re.IGNORECASE)
    match = pattern3.search(filename)
    if match:
        episode = int(match.group(1))
        return {
            "season": 1,  # Default to season 1
            "episode": episode,
            "episode_name": None
        }
    
    return None


def extract_episode_info_fallback(filename: str) -> Optional[Dict[str, Any]]:
    """
    Fallback episode extraction using guessit library.
    
    Args:
        filename: Video filename
        
    Returns:
        Dictionary with season, episode, and episode name
    """
    try:
        from guessit import guessit
        
        guess = guessit(filename)
        
        if 'episode' in guess:
            return {
                "season": guess.get('season', 1),
                "episode": guess['episode'] if isinstance(guess['episode'], int) else guess['episode'][0],
                "episode_name": guess.get('episode_title', None)
            }
    except ImportError:
        print("guessit not installed, skipping fallback parsing")
    except Exception as e:
        print(f"Error using guessit: {e}")
    
    return None


def parse_episode_info(filename: str) -> Optional[Dict[str, Any]]:
    """
    Parse episode information using hybrid approach.
    Try common patterns first, then fallback to guessit.
    
    Args:
        filename: Video filename
        
    Returns:
        Dictionary with season, episode, and optionally episode name
    """
    # Try common patterns first
    info = extract_episode_info(filename)
    if info:
        return info
    
    # Fallback to guessit
    return extract_episode_info_fallback(filename)


def detect_subtitle_language(filename: str) -> Optional[str]:
    """
    Detect subtitle language from filename.
    
    Args:
        filename: Subtitle filename
        
    Returns:
        Language code (e.g., 'en', 'es') or None
    """
    # Common patterns: movie.en.srt, movie.eng.srt, movie.english.srt
    language_patterns = [
        (r'\.([a-z]{2})\.(srt|ass|sub|vtt)$', 1),  # .en.srt
        (r'\.([a-z]{3})\.(srt|ass|sub|vtt)$', 1),  # .eng.srt
    ]
    
    filename_lower = filename.lower()
    
    for pattern, group in language_patterns:
        match = re.search(pattern, filename_lower)
        if match:
            lang_code = match.group(group)
            
            # Convert 3-letter codes to 2-letter
            lang_map = {
                'eng': 'en', 'spa': 'es', 'fre': 'fr', 'ger': 'de',
                'ita': 'it', 'por': 'pt', 'rus': 'ru', 'jpn': 'ja',
                'chi': 'zh', 'kor': 'ko', 'ara': 'ar', 'hin': 'hi'
            }
            
            return lang_map.get(lang_code, lang_code)
    
    # Check for full language names
    language_names = {
        'english': 'en', 'spanish': 'es', 'french': 'fr', 'german': 'de',
        'italian': 'it', 'portuguese': 'pt', 'russian': 'ru', 'japanese': 'ja',
        'chinese': 'zh', 'korean': 'ko', 'arabic': 'ar', 'hindi': 'hi'
    }
    
    for lang_name, lang_code in language_names.items():
        if lang_name in filename_lower:
            return lang_code
    
    return None


def is_forced_subtitle(filename: str) -> bool:
    """
    Check if subtitle is marked as forced.
    
    Args:
        filename: Subtitle filename
        
    Returns:
        True if forced subtitle
    """
    return 'forced' in filename.lower()


def format_plex_subtitle_name(base_name: str, language: Optional[str] = None, 
                              forced: bool = False, ext: str = '.srt') -> str:
    """
    Format subtitle filename according to Plex conventions.
    
    Args:
        base_name: Base video filename without extension
        language: Language code (e.g., 'en')
        forced: Whether subtitle is forced
        ext: Subtitle extension
        
    Returns:
        Formatted subtitle filename
    """
    # Format: Movie.srt (default), Movie.en.srt, Movie.en.forced.srt
    parts = [base_name]
    
    if language:
        parts.append(language)
    
    if forced:
        parts.append('forced')
    
    return '.'.join(parts) + ext


def format_plex_episode_name(show_title: str, season: int, episode: int,
                             episode_name: Optional[str] = None, ext: str = '.mkv') -> str:
    """
    Format episode filename according to Plex conventions.
    
    Args:
        show_title: TV show title
        season: Season number
        episode: Episode number
        episode_name: Optional episode title
        ext: File extension
        
    Returns:
        Formatted filename (e.g., 'S01E01 - Episode Name.mkv')
    """
    filename = f"S{season:02d}E{episode:02d}"
    
    if episode_name:
        # Clean episode name
        clean_name = episode_name.strip()
        # Remove problematic characters for filenames
        clean_name = re.sub(r'[<>:"/\\|?*]', '', clean_name)
        filename += f" - {clean_name}"
    
    return filename + ext
