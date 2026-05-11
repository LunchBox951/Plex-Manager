"""
qBittorrent Web API client for Plex Manager.
Handles authentication, torrent management, and metadata extraction.
"""

import os
import time
import hashlib
import requests
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse, parse_qs

from src.console import print_info, print_success, print_error, print_warning

_CB_CLOSED = "CLOSED"
_CB_OPEN = "OPEN"
_CB_HALF_OPEN = "HALF_OPEN"
_CB_THRESHOLD = 5
_CB_COOLDOWN = 300


class CircuitBreaker:
    def __init__(self):
        self.state = _CB_CLOSED
        self.failure_count = 0
        self.opened_at = None

    def record_success(self):
        if self.state != _CB_CLOSED:
            print_info("qBittorrent reachable — resuming normal operation")
        self.state = _CB_CLOSED
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self):
        if self.state == _CB_OPEN:
            return
        self.failure_count += 1
        if self.state == _CB_HALF_OPEN or self.failure_count >= _CB_THRESHOLD:
            self.state = _CB_OPEN
            self.opened_at = time.time()
            print_warning("qBittorrent unreachable — entering 5-minute cooldown")

    def allow_request(self) -> bool:
        if self.state == _CB_CLOSED:
            return True
        if self.state == _CB_OPEN:
            if time.time() - self.opened_at >= _CB_COOLDOWN:
                self.state = _CB_HALF_OPEN
                self.failure_count = 0
                return True
            return False
        return True


def _decode_bencode_value(data: bytes, idx: int) -> tuple:
    """
    Decode a single bencode value starting at idx.
    Returns (end_index, decoded_value).
    """
    if idx >= len(data):
        raise ValueError("Unexpected end of data")

    ch = data[idx:idx + 1]

    if ch == b'i':  # Integer: i<number>e
        end = data.index(b'e', idx + 1)
        return end + 1, int(data[idx + 1:end])

    if ch == b'l':  # List: l<values>e
        idx += 1
        items = []
        while data[idx:idx + 1] != b'e':
            idx, val = _decode_bencode_value(data, idx)
            items.append(val)
        return idx + 1, items

    if ch == b'd':  # Dict: d<key><value>...e
        idx += 1
        result = {}
        while data[idx:idx + 1] != b'e':
            idx, key = _decode_bencode_value(data, idx)
            idx, val = _decode_bencode_value(data, idx)
            if isinstance(key, bytes):
                key = key.decode('utf-8', errors='replace')
            result[key] = val
        return idx + 1, result

    if ch.isdigit():  # String: <length>:<data>
        colon = data.index(b':', idx)
        length = int(data[idx:colon])
        start = colon + 1
        return start + length, data[start:start + length]

    raise ValueError(f"Invalid bencode at position {idx}: {ch!r}")


def _extract_info_hash_from_torrent(data: bytes) -> Optional[str]:
    """
    Extract SHA1 info hash from raw .torrent file bytes.

    The info hash is the SHA1 of the raw bencode-encoded 'info' dictionary,
    which is the standard BitTorrent info hash used for peer identification.
    """
    try:
        # Find the raw 'info' dict boundaries for hashing
        # We need the raw bytes, not the decoded value
        marker = b'4:infod'
        idx = data.find(marker)
        if idx == -1:
            return None

        info_start = idx + 6  # position of 'd' starting the info dict
        info_end, _ = _decode_bencode_value(data, info_start)
        raw_info = data[info_start:info_end]
        return hashlib.sha1(raw_info).hexdigest().lower()
    except Exception:
        return None


class QBittorrentClient:
    """Client for interacting with qBittorrent Web API."""
    
    def __init__(self, base_url: str = None, username: str = None, password: str = None):
        """
        Initialize qBittorrent client.
        
        Args:
            base_url: qBittorrent Web UI URL (defaults to QBITTORRENT_URL env var)
            username: qBittorrent username (defaults to QBITTORRENT_USERNAME env var)
            password: qBittorrent password (defaults to QBITTORRENT_PASSWORD env var)
        """
        self.base_url = (base_url or os.getenv('QBITTORRENT_URL', 'http://localhost:8080')).rstrip('/')
        self.username = username or os.getenv('QBITTORRENT_USERNAME', 'admin')
        self.password = password or os.getenv('QBITTORRENT_PASSWORD', 'adminpass')
        self.session = requests.Session()
        self._authenticated = False
        self._cb = CircuitBreaker()
    
    def _login(self) -> bool:
        """
        Authenticate with qBittorrent Web API.

        Returns:
            True if authentication successful, False otherwise
        """
        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
                timeout=10
            )

            if response.status_code == 200 and response.text.strip() in ("Ok.", ""):
                self._authenticated = True
                self._cb.record_success()
                print_success(f"Successfully authenticated with qBittorrent at {self.base_url}")
                return True
            else:
                print_error(f"Failed to authenticate with qBittorrent: {response.text}")
                return False
        except Exception as e:
            print_error(f"Error during qBittorrent authentication: {e}")
            return False
    
    def _ensure_authenticated(self):
        """Ensure client is authenticated, login if not."""
        if not self._authenticated:
            self._login()
    
    def safe_api_call(self, method: str, endpoint: str, max_retries: int = 3, 
                     retry_delay: int = 2, **kwargs) -> Optional[requests.Response]:
        """
        Make a safe API call with authentication and retry logic.
        
        Args:
            method: HTTP method (get, post, etc.)
            endpoint: API endpoint path
            max_retries: Maximum number of retry attempts
            retry_delay: Base delay between retries in seconds
            **kwargs: Additional arguments to pass to requests
            
        Returns:
            Response object or None if all retries failed
        """
        if not self._cb.allow_request():
            return None

        self._ensure_authenticated()
        if not self._cb.allow_request():
            return None

        url = f"{self.base_url}{endpoint}"

        for attempt in range(max_retries):
            try:
                response = getattr(self.session, method)(url, timeout=30, **kwargs)

                if response.status_code == 403:
                    print_warning("Session expired, re-authenticating...")
                    self._authenticated = False
                    self._ensure_authenticated()
                    continue

                self._cb.record_success()
                return response

            except requests.exceptions.RequestException as e:
                print_warning(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}")

                if attempt < max_retries - 1:
                    sleep_time = retry_delay * (2 ** attempt)
                    print_info(f"Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                else:
                    print_error("Max retries reached, giving up")
                    self._cb.record_failure()
                    return None

        return None
    
    @staticmethod
    def extract_info_hash(magnet_link: str) -> Optional[str]:
        """
        Extract info hash from magnet link for normalization.
        
        Args:
            magnet_link: Magnet URI
            
        Returns:
            Info hash as lowercase hex string, or None if invalid
        """
        try:
            parsed = urlparse(magnet_link)
            if parsed.scheme != 'magnet':
                return None
            
            params = parse_qs(parsed.query)
            xt = params.get('xt', [])
            
            if not xt:
                return None
            
            # xt parameter format: urn:btih:<hash>
            xt_value = xt[0]
            if not xt_value.startswith('urn:btih:'):
                return None
            
            info_hash = xt_value[9:].lower()  # Remove 'urn:btih:' prefix
            return info_hash
            
        except Exception as e:
            print_error(f"Error extracting info hash: {e}")
            return None

    @staticmethod
    def resolve_info_hash(url: str) -> Optional[str]:
        """
        Resolve info hash from a magnet URI or Prowlarr download URL.

        Handles three cases:
        1. Magnet URIs - extracts hash directly from xt parameter
        2. HTTP URLs that redirect to magnet URIs - follows redirect, then extracts
        3. HTTP URLs that return .torrent files - parses bencode for info dict hash

        Args:
            url: Magnet URI or HTTP(S) download URL

        Returns:
            Info hash as lowercase hex string, or None if extraction fails
        """
        if not url:
            return None

        # Try direct magnet extraction first
        info_hash = QBittorrentClient.extract_info_hash(url)
        if info_hash:
            return info_hash

        # For HTTP URLs, try to resolve via redirect or torrent file parsing
        if not url.startswith('http'):
            return None

        try:
            response = requests.get(url, allow_redirects=True, timeout=15, stream=True)

            # Check if final URL after redirects is a magnet link
            if response.url.startswith('magnet:'):
                return QBittorrentClient.extract_info_hash(response.url)

            # Check response content for .torrent file (bencode starts with 'd')
            content = response.content
            if content and content[:1] == b'd':
                info_hash = _extract_info_hash_from_torrent(content)
                if info_hash:
                    return info_hash

        except Exception as e:
            print_warning(f"Failed to resolve info hash from URL: {e}")

        return None

    def add_magnet(self, magnet_link: str, save_path: str = None,
                   category: str = None) -> bool:
        """
        Add a magnet link or .torrent URL to qBittorrent.
        
        qBittorrent's API accepts both magnet:// URIs and HTTP(S) URLs to .torrent files.
        The server will download and parse .torrent files automatically.
        
        Args:
            magnet_link: Magnet URI or HTTP(S) URL to .torrent file
            save_path: Optional custom save path
            category: Optional category (e.g., 'movies', 'tv')
            
        Returns:
            True if added successfully, False otherwise
        """
        data = {"urls": magnet_link}
        
        if save_path:
            data["savepath"] = save_path
        if category:
            data["category"] = category
        
        response = self.safe_api_call("post", "/api/v2/torrents/add", data=data)
        
        if response and response.status_code == 200:
            if response.text == "Ok.":
                link_type = "torrent URL" if magnet_link.startswith('http') else "magnet link"
                print_success(f"Successfully added {link_type} to qBittorrent")
                return True
            else:
                print_error(f"Failed to add torrent: {response.text}")
                return False
        
        return False
    
    def get_torrent_info(self, torrent_hash: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific torrent.
        
        Args:
            torrent_hash: Torrent info hash
            
        Returns:
            Dictionary with torrent information, or None if not found
        """
        response = self.safe_api_call("get", "/api/v2/torrents/info", 
                                     params={"hashes": torrent_hash.lower()})
        
        if response and response.status_code == 200:
            torrents = response.json()
            if torrents and len(torrents) > 0:
                return torrents[0]
        
        return None
    
    def get_all_torrents(self, filter_status: str = None, 
                        category: str = None) -> List[Dict[str, Any]]:
        """
        Get list of all torrents.
        
        Args:
            filter_status: Optional filter (downloading, completed, paused, etc.)
            category: Optional category filter
            
        Returns:
            List of torrent dictionaries
        """
        params = {}
        if filter_status:
            params["filter"] = filter_status
        if category:
            params["category"] = category
        
        response = self.safe_api_call("get", "/api/v2/torrents/info", params=params)
        
        if response and response.status_code == 200:
            return response.json()
        
        return []
    
    def get_torrent_files(self, torrent_hash: str) -> List[Dict[str, Any]]:
        """
        Get list of files in a torrent.
        
        Args:
            torrent_hash: Torrent info hash
            
        Returns:
            List of file dictionaries with name, size, progress, priority
        """
        response = self.safe_api_call("get", "/api/v2/torrents/files", 
                                     params={"hash": torrent_hash.lower()})
        
        if response and response.status_code == 200:
            return response.json()
        
        return []
    
    def get_torrent_properties(self, torrent_hash: str) -> Optional[Dict[str, Any]]:
        """
        Get properties/metadata for a torrent.
        
        Args:
            torrent_hash: Torrent info hash
            
        Returns:
            Dictionary with torrent properties (save_path, creation_date, etc.)
        """
        response = self.safe_api_call("get", "/api/v2/torrents/properties", 
                                     params={"hash": torrent_hash.lower()})
        
        if response and response.status_code == 200:
            return response.json()
        
        return None
    
    def pause_torrent(self, torrent_hash: str) -> bool:
        """Pause a torrent."""
        response = self.safe_api_call("post", "/api/v2/torrents/pause", 
                                     data={"hashes": torrent_hash.lower()})
        return response and response.status_code == 200
    
    def resume_torrent(self, torrent_hash: str) -> bool:
        """Resume a paused torrent."""
        response = self.safe_api_call("post", "/api/v2/torrents/resume", 
                                     data={"hashes": torrent_hash.lower()})
        return response and response.status_code == 200
    
    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> bool:
        """
        Delete a torrent from qBittorrent.
        
        Args:
            torrent_hash: Torrent info hash
            delete_files: Whether to also delete downloaded files
            
        Returns:
            True if deleted successfully
        """
        response = self.safe_api_call("post", "/api/v2/torrents/delete", 
                                     data={
                                         "hashes": torrent_hash.lower(),
                                         "deleteFiles": str(delete_files).lower()
                                     })
        return response and response.status_code == 200
    
    def set_file_priority(self, torrent_hash: str, file_id: int, priority: int) -> bool:
        """
        Set priority for a specific file in a torrent.
        
        Args:
            torrent_hash: Torrent info hash
            file_id: File ID from get_torrent_files
            priority: Priority (0=do not download, 1=normal, 6=high, 7=maximal)
            
        Returns:
            True if set successfully
        """
        response = self.safe_api_call("post", "/api/v2/torrents/filePrio", 
                                     data={
                                         "hash": torrent_hash.lower(),
                                         "id": file_id,
                                         "priority": priority
                                     })
        return response and response.status_code == 200


# Global client instance
_qb_client = None


def get_qbittorrent_client() -> QBittorrentClient:
    """
    Get or create global qBittorrent client instance.
    
    Returns:
        QBittorrentClient instance
    """
    global _qb_client
    if _qb_client is None:
        _qb_client = QBittorrentClient()
    return _qb_client
