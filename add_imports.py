#!/usr/bin/env python3
import sys

# Read the file
with open(r'c:\Users\LunchBox\Documents\Plex Manager\src\download_monitor.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with "from filelock import FileLock, Timeout"
import_index = -1
for i, line in enumerate(lines):
    if 'from filelock import FileLock, Timeout' in line:
        import_index = i
        break

if import_index == -1:
    print("Could not find filelock import!")
    sys.exit(1)

# Insert console imports after filelock import (skip the blank line)
insert_index = import_index + 2  # After filelock and blank line
console_imports = [
    '\n',
    'from src.console import (\n',
    '    print_info, print_warning, print_error, print_debug,\n',
    '    print_monitor, print_success, print_failure\n',
    ')\n'
]

# Insert the lines
for i, imp in enumerate(console_imports):
    lines.insert(insert_index + i, imp)

# Fix the typo on line with "deletion}"
for i, line in enumerate(lines):
    if 'deletion}' in line:
        lines[i] = line.replace('deletion}', 'deletion')
        break

# Write back
with open(r'c:\Users\LunchBox\Documents\Plex Manager\src\download_monitor.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Successfully added console imports and fixed typo!")
