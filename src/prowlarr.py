"""
Prowlarr API client for unified torrent indexer searching.
Provides search capabilities across 500+ indexers with CloudFlare bypass support.
"""

import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
import requests
from dotenv import load_dotenv

from src.console import print_info, print_warning, print_error, print_debug
from src.utils import normalize_title

load_dotenv()

# Prowlarr configuration
# API Key location: Prowlarr → Settings → General → Security → API Key
PROWLARR_URL = os.getenv("PROWLARR_URL", "http://localhost:9696")
PROWLARR_API_KEY = os.getenv("PROWLARR_API_KEY")

# Prowlarr category IDs
CATEGORY_MOVIES = 2000
CATEGORY_TV = 5000


@dataclass
class TorrentResult:
    """Represents a torrent search result from Prowlarr."""
    title: str
    magnet_link: str
    info_hash: str
    size_bytes: int
    seeders: int
    leechers: int
    indexer: str
    publish_date: Optional[datetime] = None
    
    @property
    def size_gb(self) -> float:
        """Convert size to GB."""
        return self.size_bytes / (1024 ** 3)


class ProwlarrClient:
    """
    Client for interacting with Prowlarr API.
    Handles authentication, search requests, and response parsing.
    """
    
    def __init__(self, base_url: str = None, api_key: str = None):
        """
        Initialize Prowlarr client.
        
        Args:
            base_url: Prowlarr base URL (e.g., http://localhost:9696)
            api_key: Prowlarr API key for authentication
        """
        self.base_url = (base_url or PROWLARR_URL).rstrip('/')
        self.api_key = api_key or PROWLARR_API_KEY
        
        if not self.api_key:
            raise ValueError("PROWLARR_API_KEY environment variable is required")
        
        self.session = requests.Session()
        self.session.headers.update({
            'X-Api-Key': self.api_key,
            'Content-Type': 'application/json'
        })
        
        print_info(f"Initialized Prowlarr client for {self.base_url}", prefix="PROWLARR")
    
    def _make_request(self, endpoint: str, params: dict = None, max_retries: int = 3) -> dict:
        """
        Make authenticated request to Prowlarr API with retry logic.
        
        Args:
            endpoint: API endpoint path
            params: Query parameters
            max_retries: Maximum number of retry attempts
            
        Returns:
            dict: Parsed JSON response
            
        Raises:
            requests.RequestException: If request fails after all retries
        """
        url = f"{self.base_url}/api/v1/{endpoint}"
        
        for attempt in range(max_retries):
            try:
                print_debug(f"Prowlarr API request: GET {url} params={params}")
                response = self.session.get(url, params=params, timeout=300)
                response.raise_for_status()
                return response.json()
                
            except requests.RequestException as e:
                print_warning(f"Prowlarr request failed (attempt {attempt + 1}/{max_retries}): {e}")
                
                if attempt < max_retries - 1:
                    # Exponential backoff
                    sleep_time = 2 ** attempt
                    print_debug(f"Retrying in {sleep_time}s...")
                    time.sleep(sleep_time)
                else:
                    print_error(f"Prowlarr request failed after {max_retries} attempts")
                    raise
    
    def search(self, query: str, category: int) -> List[TorrentResult]:
        """
        Search for torrents across Prowlarr indexers.
        
        Args:
            query: Search query (e.g., "Inception 2010" or "Breaking Bad S01")
            category: Prowlarr category ID (2000=Movies, 5000=TV)
            
        Returns:
            List[TorrentResult]: List of torrent search results
            
        Example:
            >>> client = get_prowlarr_client()
            >>> results = client.search("Inception 2010", CATEGORY_MOVIES)
            >>> for torrent in results:
            ...     print(f"{torrent.title} - {torrent.seeders} seeders")
        """
        # Normalize query to remove special characters before searching
        query = normalize_title(query)
        
        print_info(f"Searching Prowlarr: query='{query}' category={category}", prefix="PROWLARR")
        
        params = {
            'query': query,
            'categories': category,
            'type': 'search'
        }
        
        try:
            data = self._make_request('search', params=params)
            
            if not isinstance(data, list):
                print_warning(f"Unexpected Prowlarr response format: {type(data)}")
                return []
            
            results = []
            for item in data:
                try:
                    # Extract magnet link
                    magnet_link = item.get('magnetUrl') or item.get('downloadUrl')
                    if not magnet_link:
                        print_debug(f"Skipping result without magnet/download URL: {item.get('title')}")
                        continue
                    
                    # Parse publish date if available
                    publish_date = None
                    if item.get('publishDate'):
                        try:
                            publish_date = datetime.fromisoformat(item['publishDate'].replace('Z', '+00:00'))
                        except Exception as e:
                            print_debug(f"Failed to parse publish date: {e}")
                    
                    result = TorrentResult(
                        title=item.get('title', 'Unknown'),
                        magnet_link=magnet_link,
                        info_hash=item.get('infoHash', '').lower(),
                        size_bytes=item.get('size', 0),
                        seeders=item.get('seeders', 0),
                        leechers=item.get('leechers', 0),
                        indexer=item.get('indexer', 'Unknown'),
                        publish_date=publish_date
                    )
                    
                    results.append(result)
                    
                except Exception as e:
                    print_warning(f"Failed to parse Prowlarr result: {e}")
                    continue
            
            print_info(f"Found {len(results)} torrents from Prowlarr", prefix="PROWLARR")
            return results
            
        except requests.RequestException as e:
            print_error(f"Prowlarr search failed: {e}")
            return []
    
    def test_connection(self) -> bool:
        """
        Test connection to Prowlarr API.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            data = self._make_request('system/status', max_retries=1)
            print_info(f"Prowlarr connection successful: version {data.get('version')}", prefix="PROWLARR")
            return True
        except Exception as e:
            print_error(f"Prowlarr connection test failed: {e}")
            return False


# Global client instance
_prowlarr_client: Optional[ProwlarrClient] = None


def get_prowlarr_client() -> ProwlarrClient:
    """
    Get or create global Prowlarr client instance (singleton).
    
    Returns:
        ProwlarrClient: Global Prowlarr client
    """
    global _prowlarr_client
    
    if _prowlarr_client is None:
        _prowlarr_client = ProwlarrClient()
    
    return _prowlarr_client


# Convenience function for common search patterns
def search_movie(title: str, year: int = None) -> List[TorrentResult]:
    """
    Search for movie torrents.
    
    Args:
        title: Movie title
        year: Release year (optional but recommended)
        
    Returns:
        List[TorrentResult]: Movie torrent results
    """
    query = f"{title} {year}" if year else title
    client = get_prowlarr_client()
    return client.search(query, CATEGORY_MOVIES)


def search_tv(title: str, season: int = None) -> List[TorrentResult]:
    """
    Search for TV show torrents.
    
    Args:
        title: TV show title
        season: Season number (e.g., 1 for S01)
        
    Returns:
        List[TorrentResult]: TV torrent results
    """
    if season is not None:
        query = f"{title} S{season:02d}"
    else:
        query = title
    
    client = get_prowlarr_client()
    return client.search(query, CATEGORY_TV)
