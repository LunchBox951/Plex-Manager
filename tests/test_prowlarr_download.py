"""
Test script for Prowlarr integration with scoring system.
Searches for KPOP DEMON HUNTERS and downloads the best-scoring torrent.
"""

import os
import sys
import json
import time
import logging
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.prowlarr import get_prowlarr_client, CATEGORY_MOVIES
from src.scoring import rank_torrents, select_best_torrent
from src.qbittorrent import get_qbittorrent_client, QBittorrentClient
from src.TMDB import get_movie_details
from src.database import get_db
from src.models import Download


def test_prowlarr_download():
    """Test complete workflow: Prowlarr search → Scoring → qBittorrent download."""
    
    # Movie details
    TMDB_ID = 803796
    MOVIE_TITLE = "KPOP DEMON HUNTERS"
    
    logger.info("=" * 80)
    logger.info(f"Testing Prowlarr Download Workflow for: {MOVIE_TITLE}")
    logger.info("=" * 80)
    
    try:
        # Step 1: Get TMDB metadata
        logger.info("\n[Step 1] Fetching TMDB metadata...")
        tmdb_data = get_movie_details(TMDB_ID)
        title = tmdb_data.get('title')
        year = tmdb_data.get('year')
        
        logger.info(f"✓ Found: {title} ({year})")
        logger.info(f"  Overview: {tmdb_data.get('overview', 'N/A')[:100]}...")
        
        # Step 2: Test Prowlarr connection
        logger.info("\n[Step 2] Testing Prowlarr connection...")
        prowlarr = get_prowlarr_client()
        
        if prowlarr.test_connection():
            logger.info("✓ Prowlarr connection successful")
        else:
            logger.error("✗ Prowlarr connection failed")
            return False
        
        # Step 3: Search Prowlarr
        logger.info("\n[Step 3] Searching Prowlarr...")
        query = f"{title} {year}"
        logger.info(f"  Query: {query}")
        logger.info(f"  Category: {CATEGORY_MOVIES} (Movies)")
        
        torrents = prowlarr.search(query, CATEGORY_MOVIES)
        
        if not torrents:
            logger.error("✗ No torrents found")
            return False
        
        logger.info(f"✓ Found {len(torrents)} torrents")
        
        # Display raw results
        logger.info("\n  Top 5 Raw Results:")
        for i, torrent in enumerate(torrents[:5], 1):
            logger.info(f"  {i}. {torrent.title}")
            logger.info(f"     Size: {torrent.size_gb:.2f} GB | Seeders: {torrent.seeders} | Indexer: {torrent.indexer}")
        
        # Step 4: Get failed hashes from database
        logger.info("\n[Step 4] Checking for failed torrents...")
        db = next(get_db())
        failed_downloads = db.query(Download).filter(
            Download.status.in_(['failed', 'partial_failed'])
        ).all()
        failed_hashes = {d.torrent_hash.lower() for d in failed_downloads}
        
        logger.info(f"  Found {len(failed_hashes)} failed hashes to exclude")
        
        # Step 5: Score and rank torrents
        logger.info("\n[Step 5] Scoring torrents...")
        qb = get_qbittorrent_client()
        
        scored_torrents = rank_torrents(
            torrents=torrents,
            failed_hashes=failed_hashes,
            tmdb_id=None,  # Not needed for movies
            season_number=None,
            requested_episodes=None,
            db_session=db,
            qb_client=qb
        )
        
        if not scored_torrents:
            logger.error("✗ No suitable torrents after filtering")
            return False
        
        logger.info(f"✓ Ranked {len(scored_torrents)} torrents")
        
        # Display top 5 scored results
        logger.info("\n  Top 5 Scored Results:")
        for i, scored in enumerate(scored_torrents[:5], 1):
            logger.info(f"  {i}. {scored.torrent.title}")
            logger.info(f"     Score: {scored.final_score:.2f} | {scored.reason}")
            logger.info(f"     Size: {scored.torrent.size_gb:.2f} GB | Seeders: {scored.torrent.seeders}")
        
        # Step 6: Select best torrent
        logger.info("\n[Step 6] Selecting best torrent...")
        best = select_best_torrent(scored_torrents, min_score=1.0)
        
        if not best:
            logger.error("✗ No torrent meets minimum quality requirements")
            return False
        
        logger.info(f"✓ Selected: {best.torrent.title}")
        logger.info(f"  Final Score: {best.final_score:.2f}")
        logger.info(f"  Resolution: {best.resolution or 'Unknown'}")
        logger.info(f"  Size: {best.torrent.size_gb:.2f} GB")
        logger.info(f"  Seeders: {best.torrent.seeders}")
        logger.info(f"  Indexer: {best.torrent.indexer}")
        
        # Step 7: Check for duplicates
        logger.info("\n[Step 7] Checking for duplicates...")
        
        # Debug: Log magnet link details
        logger.info(f"  Magnet link: {best.torrent.magnet_link[:100]}...")
        
        info_hash = QBittorrentClient.extract_info_hash(best.torrent.magnet_link)
        if not info_hash:
            # Try using the info_hash from torrent result directly
            info_hash = best.torrent.info_hash
            if info_hash:
                logger.warning(f"⚠ Could not extract from magnet, using torrent.info_hash: {info_hash}")
            else:
                logger.error("✗ Could not extract info hash and none provided")
                return False
        
        logger.info(f"  Info Hash: {info_hash}")
        
        existing = db.query(Download).filter(Download.torrent_hash == info_hash).first()
        if existing:
            logger.warning(f"⚠ Torrent already in database (Download ID: {existing.id})")
            logger.info(f"  Status: {existing.status}")
            logger.info(f"  Added: {existing.added_at}")
            logger.info("\nSkipping download (already exists)")
            return True
        
        # Step 8: Add to qBittorrent
        logger.info("\n[Step 8] Adding to qBittorrent...")
        
        category = "movie"
        save_path = os.getenv('DOWNLOADS_PATH', 'C:\\downloads')
        
        logger.info(f"  Category: {category}")
        logger.info(f"  Save Path: {save_path}")
        
        success = qb.add_magnet(
                    magnet_link=best.torrent.magnet_link,
            save_path=save_path
        )
        
        if not success:
            logger.error("✗ Failed to add torrent to qBittorrent")
            return False
        
        logger.info("✓ Torrent added to qBittorrent")
        
        # Wait for metadata
        logger.info("\n[Step 9] Waiting for metadata (2 seconds)...")
        time.sleep(2)
        
        # Get torrent info
        torrent_info = qb.get_torrent_info(info_hash)
        if not torrent_info:
            logger.warning("⚠ Could not retrieve torrent info immediately")
        else:
            logger.info(f"✓ Torrent metadata retrieved")
            logger.info(f"  Name: {torrent_info.get('name')}")
            logger.info(f"  State: {torrent_info.get('state')}")
            logger.info(f"  Progress: {torrent_info.get('progress', 0) * 100:.1f}%")
        
        # Step 10: Create database record
        logger.info("\n[Step 10] Creating database record...")
        
        from datetime import datetime, timedelta
        
        download = Download(
            torrent_hash=info_hash,
            magnet_link=best.torrent.magnet_link,
            status='downloading',
            media_type='movie',
            metadata_json=json.dumps({
                'name': torrent_info.get('name') if torrent_info else best.torrent.title,
                'size': best.torrent.size_bytes,
                'indexer': best.torrent.indexer,
                'score': best.final_score,
                'resolution': best.resolution
            }),
            will_timeout_at=datetime.utcnow() + timedelta(days=15),
            tmdb_id=TMDB_ID,
            year=year
        )
        
        db.add(download)
        db.commit()
        db.refresh(download)
        
        logger.info(f"✓ Database record created (Download ID: {download.id})")
        
        # Success summary
        logger.info("\n" + "=" * 80)
        logger.info("SUCCESS! Download workflow completed")
        logger.info("=" * 80)
        logger.info(f"Movie: {title} ({year})")
        logger.info(f"Torrent: {best.torrent.title}")
        logger.info(f"Score: {best.final_score:.2f}")
        logger.info(f"Size: {best.torrent.size_gb:.2f} GB")
        logger.info(f"Download ID: {download.id}")
        logger.info(f"Info Hash: {info_hash}")
        logger.info("\nMonitor progress with:")
        logger.info(f"  python -c \"from src.qbittorrent import get_qbittorrent_client; print(get_qbittorrent_client().get_torrent_info('{info_hash}'))\"")
        logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_prowlarr_download()
    sys.exit(0 if success else 1)
