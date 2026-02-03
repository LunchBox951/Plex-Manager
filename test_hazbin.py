from dotenv import load_dotenv
load_dotenv()

from src.plex import get_plex_libraries, check_media_exists

# Check all TV libraries
libs = [l for l in get_plex_libraries() if l.type == 'show']
print(f"\nFound {len(libs)} TV libraries:")

for lib in libs:
    items = lib.all()
    print(f"\n{lib.title}: {len(items)} shows")
    
    # Search for Hazbin
    hazbin = [i for i in items if 'hazbin' in i.title.lower()]
    if hazbin:
        show = hazbin[0]
        print(f"  ✓ Found: {show.title}")
        print(f"    Year: {show.year if hasattr(show, 'year') else 'N/A'}")
        print(f"    Has thumb: {bool(show.thumb) if hasattr(show, 'thumb') and show.thumb else False}")
        print(f"    Has art: {bool(show.art) if hasattr(show, 'art') and show.art else False}")
        
        if hasattr(show, 'thumb') and show.thumb:
            print(f"    Thumb path: {show.thumb}")
        if hasattr(show, 'art') and show.art:
            print(f"    Art path: {show.art}")

# Test the check_media_exists function
print("\n" + "="*50)
print("Testing check_media_exists():")
print("="*50)
result = check_media_exists('Hazbin Hotel', 2024, 'tv', season=1)
print(f"\nResult: {result}")
