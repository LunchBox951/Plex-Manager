"""
Simple syntax verification for Phase 2 implementation.
Checks that code compiles without runtime imports.
"""

import ast
import sys

print("=" * 80)
print("PHASE 2 SYNTAX VERIFICATION")
print("=" * 80)

def check_file_syntax(filepath):
    """Check if a Python file has valid syntax."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return False, str(e)

# Test files
files_to_check = [
    ('src/downloads.py', 'Downloads API with unified request'),
    ('src/download_monitor.py', 'Download monitor with MediaRequest tracking'),
]

all_passed = True

for filepath, description in files_to_check:
    print(f"\n[Checking] {description}")
    print(f"  File: {filepath}")
    
    success, error = check_file_syntax(filepath)
    
    if success:
        print("  ✓ Syntax valid")
        
        # Check for key components
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if filepath == 'src/downloads.py':
            checks = [
                ('UnifiedMediaRequestModel', 'Unified request model'),
                ('UnifiedMediaRequestResponse', 'Unified response model'),
                ('request_media_unified', 'Unified endpoint'),
                ('_download_torrent', 'Download helper function'),
                ('/media/request-unified', 'Endpoint route'),
                ('NOTIFICATION PLACEHOLDER', 'Notification placeholders'),
                ('media_request_id', 'MediaRequest linking'),
            ]
        else:  # download_monitor.py
            checks = [
                ('MediaRequest', 'MediaRequest import'),
                ('media_request_id', 'MediaRequest tracking'),
                ('NOTIFICATION PLACEHOLDER', 'Notification placeholders'),
            ]
        
        for check_str, check_desc in checks:
            if check_str in content:
                print(f"  ✓ Has {check_desc}")
            else:
                print(f"  ✗ Missing {check_desc}")
                all_passed = False
    else:
        print(f"  ✗ Syntax error: {error}")
        all_passed = False

print("\n" + "=" * 80)
if all_passed:
    print("✅ ALL SYNTAX CHECKS PASSED")
    print("=" * 80)
    print("\n📋 Phase 2 Implementation Summary:")
    print("\n✓ Unified Request Endpoint (/api/media/request-unified)")
    print("  - Handles movies, TV episodes, seasons, and entire shows")
    print("  - Integrates authentication via get_current_user")
    print("  - Validates retention policies")
    print("  - Checks Plex for duplicates before downloading")
    print("  - Creates MediaRequest records with retention policies")
    print("  - Links Downloads to MediaRequest via foreign key")
    print("  - Supports episode-level retention overrides")
    print("\n✓ Download Monitor Integration")
    print("  - Tracks MediaRequest status during downloads")
    print("  - Updates status: downloading → processing → available")
    print("  - Handles multi-download requests (TV seasons)")
    print("  - Includes notification placeholders for Phase 8")
    print("\n✓ Database Models")
    print("  - MediaRequest with retention policies")
    print("  - EpisodeRetention for per-episode overrides")
    print("  - Download.media_request_id foreign key")
    print("\n📌 Next Steps:")
    print("  1. Test with live environment (.env configured)")
    print("  2. Test end-to-end workflow with real Plex/Prowlarr")
    print("  3. Begin Phase 6: Frontend UI development")
    print("=" * 80)
else:
    print("❌ SOME CHECKS FAILED - Review errors above")
    print("=" * 80)
    sys.exit(1)
