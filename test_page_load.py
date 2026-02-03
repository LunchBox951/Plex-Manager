from dotenv import load_dotenv
load_dotenv()

from src.TMDB import get_tv_details
from src.plex import check_media_exists

# Simulate what happens when loading the media details page
print("="*60)
print("Simulating media details page load for Hazbin Hotel")
print("="*60)

# Step 1: Get TMDB data
tv = get_tv_details(94954)
title = tv.get('name')
year = tv.get('year')
print(f"\n1. TMDB Data:")
print(f"   Title: {title}")
print(f"   Year: {year}")

# Step 2: Check Plex
print(f"\n2. Checking Plex...")
plex = check_media_exists(title, year, 'tv')
print(f"   Plex Result: {plex}")

# Step 3: What should in_library be?
in_library = plex.get('exists', False)
print(f"\n3. Template Variable:")
print(f"   media.in_library = {in_library}")

# Step 4: What button should show?
if in_library:
    print(f"\n4. Button Text: 'Manage Request'")
else:
    print(f"\n4. Button Text: 'Request TV'")

print("\n" + "="*60)
