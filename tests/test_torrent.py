"""
Test script for qBittorrent torrent download functionality
"""
import time
from src.qbittorrent import QBittorrentClient

def test_torrent_download():
    """Test adding and monitoring a magnet link."""
    
    # The magnet link to test
    magnet_link = "magnet:?xt=urn:btih:EE82D207D7B7C82B10743153559D3224184F4553&dn=KPop%20Demon%20Hunters%20(2025)%201080p%20WEBRip%20x265%2010bit%205.1-LAMA&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337&tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce&tr=udp%3A%2F%2Ftracker.torrent.eu.org%3A451%2Fannounce&tr=udp%3A%2F%2Ftracker.bittor.pw%3A1337%2Fannounce&tr=udp%3A%2F%2Fpublic.popcorn-tracker.org%3A6969%2Fannounce&tr=udp%3A%2F%2Ftracker.dler.org%3A6969%2Fannounce&tr=udp%3A%2F%2Fexodus.desync.com%3A6969&tr=udp%3A%2F%2Fopen.demonii.com%3A1337%2Fannounce&tr=udp%3A%2F%2Fglotorrents.pw%3A6969%2Fannounce&tr=udp%3A%2F%2Ftracker.coppersurfer.tk%3A6969&tr=udp%3A%2F%2Ftorrent.gresille.org%3A80%2Fannounce&tr=udp%3A%2F%2Fp4p.arenabg.com%3A1337&tr=udp%3A%2F%2Ftracker.internetwarriors.net%3A1337"
    
    print("=" * 60)
    print("qBittorrent Torrent Download Test")
    print("=" * 60)
    print()
    
    # Initialize client
    print("1. Initializing qBittorrent client...")
    client = QBittorrentClient()
    
    # Extract info hash
    print("\n2. Extracting info hash from magnet link...")
    info_hash = client.extract_info_hash(magnet_link)
    if info_hash:
        print(f"   Info Hash: {info_hash}")
    else:
        print("   ERROR: Failed to extract info hash!")
        return False
    
    # Check if torrent already exists
    print("\n3. Checking if torrent already exists...")
    existing = client.get_torrent_info(info_hash)
    if existing:
        print(f"   Torrent already exists: {existing.get('name', 'Unknown')}")
        print(f"   Status: {existing.get('state', 'Unknown')}")
        print(f"   Progress: {existing.get('progress', 0) * 100:.2f}%")
        
        # Ask if we should continue monitoring it
        response = input("\n   Continue monitoring existing torrent? (y/n): ")
        if response.lower() != 'y':
            print("\n   Would you like to delete it and start fresh? (y/n): ", end='')
            delete_response = input()
            if delete_response.lower() == 'y':
                print("   Deleting existing torrent...")
                client.delete_torrent(info_hash, delete_files=True)
                time.sleep(2)
            else:
                return False
    
    # Add magnet link
    print("\n4. Adding magnet link to qBittorrent...")
    success = client.add_magnet(magnet_link, category="test")
    
    if not success:
        print("   ERROR: Failed to add magnet link!")
        return False
    
    print("   Successfully added torrent!")
    
    # Wait a moment for qBittorrent to process
    time.sleep(2)
    
    # Get torrent info
    print("\n5. Fetching torrent information...")
    torrent_info = client.get_torrent_info(info_hash)
    
    if not torrent_info:
        print("   ERROR: Could not retrieve torrent info!")
        return False
    
    print(f"\n   Torrent Name: {torrent_info.get('name', 'Unknown')}")
    print(f"   Size: {torrent_info.get('size', 0) / (1024**3):.2f} GB")
    print(f"   State: {torrent_info.get('state', 'Unknown')}")
    print(f"   Progress: {torrent_info.get('progress', 0) * 100:.2f}%")
    print(f"   Download Speed: {torrent_info.get('dlspeed', 0) / (1024**2):.2f} MB/s")
    print(f"   Upload Speed: {torrent_info.get('upspeed', 0) / (1024**2):.2f} MB/s")
    print(f"   Seeds: {torrent_info.get('num_seeds', 0)}")
    print(f"   Peers: {torrent_info.get('num_leechs', 0)}")
    
    # Get torrent properties
    print("\n6. Fetching torrent properties...")
    properties = client.get_torrent_properties(info_hash)
    
    if properties:
        print(f"   Save Path: {properties.get('save_path', 'Unknown')}")
        print(f"   Total Size: {properties.get('total_size', 0) / (1024**3):.2f} GB")
        print(f"   Pieces: {properties.get('pieces_num', 0)}")
    
    # Get file list
    print("\n7. Fetching file list...")
    files = client.get_torrent_files(info_hash)
    
    if files:
        print(f"   Found {len(files)} file(s):")
        for idx, file in enumerate(files, 1):
            file_name = file.get('name', 'Unknown')
            file_size = file.get('size', 0) / (1024**3)
            file_progress = file.get('progress', 0) * 100
            print(f"     {idx}. {file_name}")
            print(f"        Size: {file_size:.2f} GB | Progress: {file_progress:.2f}%")
    
    # Monitor download progress
    print("\n8. Monitoring download progress...")
    print("   (Press Ctrl+C to stop monitoring)\n")
    
    try:
        last_progress = 0
        while True:
            torrent_info = client.get_torrent_info(info_hash)
            
            if not torrent_info:
                print("   ERROR: Lost connection to torrent!")
                break
            
            progress = torrent_info.get('progress', 0) * 100
            state = torrent_info.get('state', 'Unknown')
            dl_speed = torrent_info.get('dlspeed', 0) / (1024**2)
            ul_speed = torrent_info.get('upspeed', 0) / (1024**2)
            eta = torrent_info.get('eta', 0)
            
            # Only print if progress changed
            if abs(progress - last_progress) >= 0.1 or progress == 100:
                eta_str = f"{eta // 3600}h {(eta % 3600) // 60}m" if eta > 0 and eta < 8640000 else "Unknown"
                print(f"   [{state}] Progress: {progress:.2f}% | "
                      f"DL: {dl_speed:.2f} MB/s | UL: {ul_speed:.2f} MB/s | "
                      f"ETA: {eta_str}")
                last_progress = progress
            
            # Check if completed
            if state == "uploading" or progress >= 100:
                print("\n   Torrent download completed!")
                break
            
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("\n\n   Monitoring stopped by user.")
    
    # Final status
    print("\n9. Final torrent status...")
    final_info = client.get_torrent_info(info_hash)
    
    if final_info:
        print(f"   Name: {final_info.get('name', 'Unknown')}")
        print(f"   State: {final_info.get('state', 'Unknown')}")
        print(f"   Progress: {final_info.get('progress', 0) * 100:.2f}%")
        print(f"   Downloaded: {final_info.get('downloaded', 0) / (1024**3):.2f} GB")
        print(f"   Uploaded: {final_info.get('uploaded', 0) / (1024**3):.2f} GB")
    
    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    try:
        test_torrent_download()
    except Exception as e:
        print(f"\nERROR: Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
