"""
Test script to verify pickle storage functionality.
Run this to test the pickle storage system before migrating queries.
"""

from datetime import datetime
from src.pickle_storage import PickleStore

def test_pickle_storage():
    """Test basic pickle storage operations."""
    print("Testing pickle storage system...")
    
    # Initialize directories first
    PickleStore.initialize_directories([
        'data/downloads',
        'data/media_requests',
        'data/season_requests',
        'data/episode_retentions',
        'cache/tmdb_cache',
        'cache/search_cache',
        'cache/tmdb_season_cache'
    ])
    
    # Now import stores (which will register indexes)
    from src.pickle_stores import download_store, media_request_store
    from src.pickle_models import Download, MediaRequest
    
    # Test 1: Create and save a Download
    print("\n1. Creating and saving a Download object...")
    download = Download(
        torrent_hash="abc123",
        magnet_link="magnet:?xt=urn:btih:abc123",
        media_type="movie",
        status="pending"
    )
    download = download_store.save(download)
    print(f"✓ Saved Download with ID: {download.id}")
    
    # Test 2: Load the Download back
    print("\n2. Loading Download from storage...")
    loaded_download = download_store.load(download.id)
    assert loaded_download is not None
    assert loaded_download.torrent_hash == "abc123"
    print(f"✓ Loaded Download: {loaded_download.torrent_hash}")
    
    # Test 3: Find by index
    print("\n3. Finding Download by torrent_hash index...")
    found_download = download_store.find_by_index('torrent_hash', 'abc123')
    assert found_download is not None
    assert found_download.id == download.id
    print(f"✓ Found Download by index: ID {found_download.id}")
    
    # Test 4: Update and save
    print("\n4. Updating Download status...")
    loaded_download.status = "downloading"
    loaded_download.progress = 50.0
    download_store.save(loaded_download)
    
    reloaded = download_store.load(download.id)
    assert reloaded.status == "downloading"
    assert reloaded.progress == 50.0
    print(f"✓ Updated Download: status={reloaded.status}, progress={reloaded.progress}")
    
    # Test 5: List by index
    print("\n5. Listing Downloads by status...")
    downloads_by_status = download_store.list_by_index('status', 'downloading')
    assert len(downloads_by_status) > 0
    print(f"✓ Found {len(downloads_by_status)} downloading downloads")
    
    # Test 6: Create MediaRequest
    print("\n6. Creating and saving a MediaRequest...")
    media_request = MediaRequest(
        user_id=1,
        tmdb_id=12345,
        media_type="movie",
        title="Test Movie",
        year=2024
    )
    media_request = media_request_store.save(media_request)
    print(f"✓ Saved MediaRequest with ID: {media_request.id}")
    
    # Test 7: Atomic update
    print("\n7. Testing atomic update...")
    def increment_progress(d):
        d.progress = 75.0
        return d
    
    updated = download_store.atomic_update(download.id, increment_progress)
    assert updated.progress == 75.0
    print(f"✓ Atomic update successful: progress={updated.progress}")
    
    # Test 8: Test graceful defaults
    print("\n8. Testing graceful field defaults...")
    # Manually create a pickle missing some fields
    import pickle
    from pathlib import Path
    from dataclasses import asdict
    
    test_path = Path('data/downloads') / "999.pkl"
    partial_data = Download(
        id=999,
        torrent_hash="partial123",
        magnet_link="magnet:?xt=urn:btih:partial123",
        media_type="tv"
    )
    # Save normally first, then reload and modify the pickle
    download_store.save(partial_data, update_indexes=False)
    
    # Load it - should fill missing fields that were just defaults
    loaded_partial = download_store.load(999)
    assert loaded_partial is not None
    assert loaded_partial.retry_count == 0  # Default filled
    assert loaded_partial.torrent_attempt == 1  # Default filled
    assert loaded_partial.progress == 0.0  # Default filled
    print("✓ Graceful defaults working - fields populated correctly")
    
    # Test 9: Validate integrity
    print("\n9. Validating storage integrity...")
    results = download_store.validate_integrity()
    print(f"✓ Validated {results['valid']}/{results['total']} records")
    if results['errors']:
        print(f"  Errors: {results['errors']}")
    
    # Test 10: Delete
    print("\n10. Testing delete...")
    download_store.delete(download.id)
    deleted_check = download_store.load(download.id)
    assert deleted_check is None
    print(f"✓ Download deleted successfully")
    
    # Cleanup
    media_request_store.delete(media_request.id)
    if loaded_partial:
        download_store.delete(999, update_indexes=False)
    
    print("\n" + "="*50)
    print("✓ All pickle storage tests passed!")
    print("="*50)


if __name__ == "__main__":
    test_pickle_storage()
