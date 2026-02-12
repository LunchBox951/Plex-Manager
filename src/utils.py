"""
Utility functions for the Plex Manager application.
Provides common helper functions used across multiple modules.
"""

import re


def normalize_title(text: str) -> str:
    """
    Normalize title by removing special characters that are invalid for file systems
    or problematic for torrent searches.
    
    Replaces special characters with spaces and prevents consecutive spaces.
    
    Args:
        text: Title to normalize
        
    Returns:
        Normalized title with special characters replaced by spaces
        
    Examples:
        >>> normalize_title("Spider-Man: No Way Home")
        "Spider-Man No Way Home"
        >>> normalize_title("Batman: The Brave and the Bold")
        "Batman The Brave and the Bold"
        >>> normalize_title("Samantha Who?")
        "Samantha Who"
    """
    # Replace special characters with space
    # Characters: < > : " / \ | ? *
    text = re.sub(r'[<>:"/\\|?*]', ' ', text)
    
    # Collapse multiple consecutive spaces to single space
    text = re.sub(r'\s+', ' ', text)
    
    # Remove leading/trailing whitespace
    return text.strip()
