"""Quick check to verify Prowlarr configuration and connectivity."""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
import requests

load_dotenv()

PROWLARR_URL = os.getenv("PROWLARR_URL", "http://localhost:9696")
PROWLARR_API_KEY = os.getenv("PROWLARR_API_KEY")

print("=" * 80)
print("PROWLARR CONFIGURATION CHECK")
print("=" * 80)
print(f"Prowlarr URL: {PROWLARR_URL}")
print(f"API Key: {'✓ Set' if PROWLARR_API_KEY else '✗ Not set'}")
print()

if not PROWLARR_API_KEY:
    print("ERROR: PROWLARR_API_KEY not found in .env file")
    print("Add it with: PROWLARR_API_KEY=your_api_key_here")
    sys.exit(1)

# Test connection
print("Testing connection...")
try:
    response = requests.get(
        f"{PROWLARR_URL}/api/v1/indexer",
        headers={"X-Api-Key": PROWLARR_API_KEY},
        timeout=10
    )
    response.raise_for_status()
    indexers = response.json()
    
    print(f"✓ Connected to Prowlarr")
    print(f"✓ Found {len(indexers)} indexers")
    print()
    
    if len(indexers) == 0:
        print("WARNING: No indexers configured in Prowlarr!")
        print("You need to add indexers in: Prowlarr → Indexers → Add Indexer")
    else:
        enabled = [idx for idx in indexers if idx.get('enable', False)]
        print(f"Enabled indexers: {len(enabled)}")
        print()
        print("Sample indexers:")
        for idx in enabled[:5]:
            print(f"  • {idx.get('name')} (ID: {idx.get('id')})")
        
        if len(enabled) < len(indexers):
            print(f"\n⚠ {len(indexers) - len(enabled)} indexers are disabled")
    
    # Test search
    print("\n" + "=" * 80)
    print("Testing search functionality...")
    try:
        search_response = requests.get(
            f"{PROWLARR_URL}/api/v1/search",
            params={
                "query": "Breaking Bad",
                "categories": [5000],  # TV category
                "type": "search"
            },
            headers={"X-Api-Key": PROWLARR_API_KEY},
            timeout=30
        )
        search_response.raise_for_status()
        results = search_response.json()
        
        print(f"✓ Search executed successfully")
        print(f"✓ Found {len(results)} torrents for 'Breaking Bad'")
        
        if len(results) > 0:
            print("\nSample results:")
            for result in results[:3]:
                print(f"  • {result.get('title')}")
                print(f"    Seeders: {result.get('seeders', 0)} | Size: {result.get('size', 0) / (1024**3):.2f} GB")
        else:
            print("\n⚠ No torrents found - indexers may not have this content")
            
    except requests.exceptions.RequestException as e:
        print(f"✗ Search failed: {e}")
        
except requests.exceptions.RequestException as e:
    print(f"✗ Connection failed: {e}")
    print("\nTroubleshooting:")
    print("  1. Is Prowlarr running? Check http://localhost:9696")
    print("  2. Is the API key correct in .env file?")
    print("  3. Is the PROWLARR_URL correct?")
    sys.exit(1)

print("\n" + "=" * 80)
print("✓ Prowlarr is configured and operational")
print("=" * 80)
