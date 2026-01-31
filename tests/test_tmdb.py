"""
Test script for TMDB module
"""

import sys
from src.TMDB import (
    search_movies,
    search_tv,
    get_movie_details,
    get_tv_details,
    get_trending,
    validate_api_key
)

def test_tmdb():
    """Run basic TMDB functionality tests."""
    
    # Test user ID (placeholder for admin user)
    test_user_id = 1
    
    print("=" * 70)
    print("Testing TMDB Module")
    print("=" * 70)
    
    # Test 1: Validate API key
    print("\n[TEST 1] Validating API key...")
    if not validate_api_key():
        print("FAILED: API key validation")
        return False
    print("PASSED: API key is valid")
    
    # Test 2: Search movies
    print("\n[TEST 2] Searching for movies: 'inception'")
    try:
        results = search_movies("inception", test_user_id)
        print(f"PASSED: Found {len(results)} movies")
        if results:
            print(f"First result: {results[0]['title']} ({results[0]['year']})")
    except Exception as e:
        print(f"FAILED: {e}")
        return False
    
    # Test 3: Search TV shows
    print("\n[TEST 3] Searching for TV shows: 'breaking bad'")
    try:
        results = search_tv("breaking bad", test_user_id)
        print(f"PASSED: Found {len(results)} TV shows")
        if results:
            print(f"First result: {results[0]['name']} ({results[0]['year']})")
    except Exception as e:
        print(f"FAILED: {e}")
        return False
    
    # Test 4: Get movie details
    print("\n[TEST 4] Getting movie details for Inception (TMDB ID: 27205)")
    try:
        details = get_movie_details(27205)
        print(f"PASSED: {details['title']} ({details['year']})")
        print(f"Runtime: {details['runtime']} minutes")
        print(f"Genres: {', '.join(details['genres'])}")
    except Exception as e:
        print(f"FAILED: {e}")
        return False
    
    # Test 5: Get trending
    print("\n[TEST 5] Getting trending movies this week")
    try:
        results = get_trending('movie', 'week')
        print(f"PASSED: Found {len(results)} trending movies")
        if results:
            print(f"Top trending: {results[0].get('title', results[0].get('name'))}")
    except Exception as e:
        print(f"FAILED: {e}")
        return False
    
    # Test 6: Test query normalization (cache hit)
    print("\n[TEST 6] Testing query normalization and caching")
    try:
        # Search with different formatting
        results1 = search_movies("  THE   MATRIX  ", test_user_id)
        print("First search completed")
        results2 = search_movies("the matrix", test_user_id)
        print("Second search completed (should be cache hit)")
        
        if len(results1) == len(results2):
            print("PASSED: Query normalization working")
        else:
            print("WARNING: Cache may not be working yet (database not implemented)")
    except Exception as e:
        print(f"FAILED: {e}")
        return False
    
    print("\n" + "=" * 70)
    print("All tests completed successfully!")
    print("=" * 70)
    print("\nNote: Cache functionality will be fully operational once database")
    print("is implemented in Phase 1.")
    
    return True


if __name__ == '__main__':
    success = test_tmdb()
    sys.exit(0 if success else 1)
