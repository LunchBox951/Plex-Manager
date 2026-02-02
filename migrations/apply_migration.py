"""
Apply database migration for calendar and retry fields.
"""
import sqlite3
import os

# Get database path
db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'plex_manager.db')
migration_path = os.path.join(os.path.dirname(__file__), '..', 'migrations', 'add_calendar_and_retry_fields.sql')

print(f"Database: {db_path}")
print(f"Migration: {migration_path}")

# Read migration SQL
with open(migration_path, 'r') as f:
    migration_sql = f.read()

# Connect and execute
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Split migration into individual statements and execute
    statements = [s.strip() for s in migration_sql.split(';') if s.strip() and not s.strip().startswith('--')]
    
    for statement in statements:
        if statement:
            print(f"\nExecuting: {statement[:60]}...")
            try:
                cursor.execute(statement)
                print("✓ Success")
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print(f"⚠ Skipped (already exists): {e}")
                else:
                    raise
    
    conn.commit()
    print("\n✅ Migration completed successfully!")
    
except Exception as e:
    print(f"\n❌ Migration failed: {e}")
    conn.rollback()
    raise
finally:
    conn.close()
