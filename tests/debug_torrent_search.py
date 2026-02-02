"""Debug script to trace torrent search and scoring."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from src.prowlarr import ProwlarrClient, CATEGORY_TV
from src.scoring import rank_torrents
from src.qbittorrent import QBittorrentClient
from src.database import SessionLocal

load_dotenv()

print("=" * 80)
print("TORRENT SEARCH DEBUG")
print("=" * 80)

# Initialize clients
prowlarr = ProwlarrClient()
qb = QBittorrentClient()
db = SessionLocal()

# Search for Breaking Bad S01
query = "Breaking Bad S01"
print(f"\nSearching: {query}")
print(f"Category: TV ({CATEGORY_TV})")

try:
    torrents = prowlarr.search(query, CATEGORY_TV)
    print(f"\n✓ Found {len(torrents)} raw torrents from Prowlarr")
    
    if len(torrents) == 0:
        print("ERROR: No torrents returned from Prowlarr!")
        sys.exit(1)
    
    # Show first 3 raw results
    print("\nSample raw torrents:")
    for i, t in enumerate(torrents[:3], 1):
        print(f"\n  {i}. {t.title}")
        print(f"     Seeders: {t.seeders} | Size: {t.size_gb:.2f} GB | Indexer: {t.indexer}")
        print(f"     Hash: {t.info_hash[:16]}...")
    
    # Now try scoring
    print("\n" + "=" * 80)
    print("SCORING TORRENTS")
    print("=" * 80)
    
    failed_hashes = set()
    scored_torrents = rank_torrents(
        torrents=torrents,
        failed_hashes=failed_hashes,
        tmdb_id=1396,  # Breaking Bad
        season_number=1,
        requested_episodes=None,
        db_session=db,
        qb_client=qb
    )
    
    print(f"\n✓ Scored torrents: {len(scored_torrents)}")
    
    if len(scored_torrents) == 0:
        print("\nERROR: All torrents filtered out during scoring!")
        print("Possible reasons:")
        print("  - All torrents below minimum seeders threshold")
        print("  - All torrents are blocked quality (CAM, TS, etc.)")
        print("  - Season pack filtering too aggressive")
        print("  - File validation rejecting all torrents")
    else:
        print("\nTop 5 scored torrents:")
        for i, st in enumerate(scored_torrents[:5], 1):
            print(f"\n  {i}. Score: {st.final_score:.2f} | {st.torrent.title}")
            print(f"     Seeders: {st.torrent.seeders} | Size: {st.torrent.size_gb:.2f} GB")
            print(f"     Resolution: {st.resolution} | Season Pack: {st.is_season_pack}")
            if st.penalty_reasons:
                print(f"     Penalties: {', '.join(st.penalty_reasons)}")
    
except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()

print("\n" + "=" * 80)
