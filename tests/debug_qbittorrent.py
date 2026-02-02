"""Test qBittorrent connectivity and magnet adding."""

import os
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from src.qbittorrent import QBittorrentClient

load_dotenv()

print("=" * 80)
print("QBITTORRENT DEBUG")
print("=" * 80)

qb = QBittorrentClient()

# Test 1: Connection
print("\n1. Testing connection...")
try:
    torrents = qb.get_all_torrents()
    print(f"   ✓ Connected to qBittorrent")
    print(f"   ✓ Current torrents: {len(torrents)}")
except Exception as e:
    print(f"   ✗ Connection failed: {e}")
    sys.exit(1)

# Test 2: Try adding a well-known public domain torrent
print("\n2. Testing magnet add functionality...")
# Ubuntu torrent (public domain, guaranteed to have seeders)
test_magnet = "magnet:?xt=urn:btih:14ffe6dd23188d7ebecef1446c7dcbad66ab3f3e&dn=ubuntu-24.04-desktop-amd64.iso"

try:
    success = qb.add_magnet(
        magnet_uri=test_magnet,
        category="test",
        save_path=os.getenv('DOWNLOADS_PATH', 'C:\\Downloads')
    )
    
    if success:
        print(f"   ✓ Magnet accepted by qBittorrent")
        
        # Extract hash
        info_hash = QBittorrentClient.extract_info_hash(test_magnet)
        print(f"   Info hash: {info_hash}")
        
        # Wait a moment for it to appear
        print("\n3. Waiting 3 seconds for torrent to appear...")
        time.sleep(3)
        
        # Try to get info
        torrent_info = qb.get_torrent_info(info_hash)
        if torrent_info:
            print(f"   ✓ Torrent found in qBittorrent")
            print(f"   State: {torrent_info.get('state')}")
            print(f"   Progress: {torrent_info.get('progress', 0) * 100:.1f}%")
        else:
            print(f"   ✗ Torrent not found after 3 seconds")
            print("   This suggests qBittorrent needs more time to connect to peers")
        
        # Try getting files
        files = qb.get_torrent_files(info_hash)
        if files:
            print(f"   ✓ Got file list ({len(files)} files)")
        else:
            print(f"   ✗ No files yet (metadata not downloaded)")
        
        # Clean up
        print("\n4. Cleaning up test torrent...")
        qb.delete_torrent(info_hash, delete_files=True)
        print("   ✓ Test torrent removed")
        
    else:
        print(f"   ✗ qBittorrent rejected magnet")
        print("   Possible reasons:")
        print("     - Invalid magnet format")
        print("     - qBittorrent not running")
        print("     - API permissions issue")
        
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("DIAGNOSIS:")
print("=" * 80)
print("If the torrent was accepted but not found after 3 seconds,")
print("that means the retry logic needs to wait longer for metadata")
print("to download. The async await fix should help with this.")
print("=" * 80)
