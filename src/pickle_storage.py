"""
Pickle-based storage system with per-file locking and graceful field defaults.
Provides CRUD operations, indexing, and atomic updates for non-SQL models.
"""

import os
import pickle
import tempfile
from dataclasses import is_dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Callable, Type, TypeVar
from filelock import FileLock, Timeout

from src.console import print_error, print_warning

# Environment configuration
PICKLE_LOCK_TIMEOUT = float(os.getenv('PICKLE_LOCK_TIMEOUT', '5.0'))
PICKLE_LOCK_RETRIES = int(os.getenv('PICKLE_LOCK_RETRIES', '3'))

T = TypeVar('T')


class PickleLockError(Exception):
    """Raised when unable to acquire file lock after retries."""
    pass


class PickleStore:
    """
    Storage manager for pickle-based model persistence.
    
    Features:
    - Per-file locking for thread-safe concurrent access
    - Atomic writes via temp file + os.replace()
    - Auto-incrementing ID generation
    - Index management for fast lookups
    - Graceful field defaults via model.fill_missing_fields()
    """
    
    def __init__(self, store_name: str, model_class: Type[T]):
        """
        Initialize pickle store.
        
        Args:
            store_name: Store path (e.g., 'data/downloads', 'cache/tmdb_cache')
            model_class: Dataclass type for this store
        """
        self.store_name = store_name
        self.model_class = model_class
        self.base_path = Path(store_name)
        self.base_path.mkdir(parents=True, exist_ok=True)
        
        # Index tracking: field_name -> index file path
        self.indexes: Dict[str, Path] = {}
    
    def _get_file_path(self, record_id: int) -> Path:
        """Get pickle file path for record ID."""
        return self.base_path / f"{record_id}.pkl"
    
    def _get_lock_path(self, record_id: int) -> Path:
        """Get lock file path for record ID."""
        return self.base_path / f"{record_id}.lock"
    
    def _get_next_id_path(self) -> Path:
        """Get path to next ID counter file."""
        return self.base_path / "next_id.pkl"
    
    def _get_index_path(self, field_name: str) -> Path:
        """Get path to index file for field."""
        return self.base_path / f"index_{field_name}.pkl"
    
    def _acquire_lock(self, lock_path: Path, timeout: float = PICKLE_LOCK_TIMEOUT) -> FileLock:
        """
        Acquire file lock with retries.
        
        Args:
            lock_path: Path to lock file
            timeout: Timeout per attempt in seconds
            
        Returns:
            Acquired FileLock
            
        Raises:
            PickleLockError: If unable to acquire lock after retries
        """
        lock = FileLock(str(lock_path), timeout=timeout)
        
        for attempt in range(1, PICKLE_LOCK_RETRIES + 1):
            try:
                lock.acquire(timeout=timeout)
                return lock
            except Timeout:
                if attempt == PICKLE_LOCK_RETRIES:
                    error_msg = f"Failed to acquire lock on {self.store_name}/{lock_path.name} after {PICKLE_LOCK_RETRIES} retries"
                    print_error(error_msg, prefix="LOCK")
                    raise PickleLockError(error_msg)
                # Silent retry
        
        return lock
    
    def _write_pickle_atomic(self, path: Path, data: Any):
        """
        Write pickle file atomically using temp file + rename.
        
        Args:
            path: Destination file path
            data: Object to pickle
        """
        # Write to temp file in same directory
        temp_fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
        try:
            with os.fdopen(temp_fd, 'wb') as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
            
            # Atomic rename
            os.replace(temp_path, path)
        except Exception as e:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except:
                pass
            raise e
    
    def _read_pickle(self, path: Path) -> Any:
        """
        Read and unpickle file.
        
        Args:
            path: File to read
            
        Returns:
            Unpickled object
        """
        with open(path, 'rb') as f:
            return pickle.load(f)
    
    def _fill_missing_fields(self, data: Any) -> Any:
        """
        Fill missing fields in loaded object using model's fill_missing_fields method.
        
        Args:
            data: Loaded object (may be missing fields)
            
        Returns:
            Object with all fields populated
        """
        if not hasattr(data, '__dict__'):
            return data
        
        # Convert to dict, fill missing fields, reconstruct
        data_dict = data.__dict__.copy()
        
        # Call model's fill_missing_fields if available
        if hasattr(self.model_class, 'fill_missing_fields'):
            data_dict = self.model_class.fill_missing_fields(data_dict)
        
        # Ensure all dataclass fields exist
        if is_dataclass(self.model_class):
            for field in fields(self.model_class):
                if field.name not in data_dict:
                    # Use field default or default_factory
                    if field.default is not field.default_factory:
                        data_dict[field.name] = field.default
                    elif field.default_factory is not field.default_factory:  # type: ignore
                        data_dict[field.name] = field.default_factory()  # type: ignore
                    else:
                        data_dict[field.name] = None
        
        # Reconstruct object
        try:
            return self.model_class(**data_dict)
        except Exception as e:
            print_warning(f"Could not reconstruct {self.model_class.__name__}: {e}", prefix="PICKLE")
            # Return original data if reconstruction fails
            return data
    
    def get_next_id(self) -> int:
        """
        Get next auto-increment ID.
        
        Returns:
            Next available ID
        """
        next_id_path = self._get_next_id_path()
        lock_path = self.base_path / "next_id.lock"
        lock = self._acquire_lock(lock_path)
        
        try:
            if next_id_path.exists():
                current_id = self._read_pickle(next_id_path)
            else:
                current_id = 1
            
            next_id = current_id + 1
            self._write_pickle_atomic(next_id_path, next_id)
            return current_id
        finally:
            lock.release()
    
    def load(self, record_id: int) -> Optional[T]:
        """
        Load record by ID with graceful field filling.
        
        Args:
            record_id: Record ID to load
            
        Returns:
            Model instance or None if not found
        """
        file_path = self._get_file_path(record_id)
        
        if not file_path.exists():
            return None
        
        lock_path = self._get_lock_path(record_id)
        lock = self._acquire_lock(lock_path)
        
        try:
            data = self._read_pickle(file_path)
            return self._fill_missing_fields(data)
        except Exception as e:
            print_error(f"Error loading {self.store_name}/{record_id}.pkl: {e}", prefix="PICKLE")
            return None
        finally:
            lock.release()
    
    def save(self, obj: T, update_indexes: bool = True) -> T:
        """
        Save record with auto-ID assignment and index updates.
        
        Args:
            obj: Model instance to save
            update_indexes: Whether to update indexes (default True)
            
        Returns:
            Saved object (with ID assigned if new)
        """
        # Assign ID if new record
        if not hasattr(obj, 'id') or obj.id is None:
            obj.id = self.get_next_id()
        
        file_path = self._get_file_path(obj.id)
        lock_path = self._get_lock_path(obj.id)
        lock = self._acquire_lock(lock_path)
        
        try:
            # Load old version for index comparison if exists
            old_obj = None
            if file_path.exists() and update_indexes:
                try:
                    old_obj = self._read_pickle(file_path)
                except:
                    pass
            
            # Write new version
            self._write_pickle_atomic(file_path, obj)
            
            # Update indexes if enabled
            if update_indexes:
                self._update_indexes_for_record(obj, old_obj)
            
            return obj
        finally:
            lock.release()
    
    def delete(self, record_id: int, update_indexes: bool = True):
        """
        Delete record and update indexes.
        
        Args:
            record_id: ID to delete
            update_indexes: Whether to update indexes (default True)
        """
        file_path = self._get_file_path(record_id)
        lock_path = self._get_lock_path(record_id)
        
        if not file_path.exists():
            return
        
        lock = self._acquire_lock(lock_path)
        
        try:
            # Load for index removal if needed
            old_obj = None
            if update_indexes:
                try:
                    old_obj = self._read_pickle(file_path)
                except:
                    pass
            
            # Delete pickle file
            file_path.unlink()
            
            # Update indexes
            if update_indexes and old_obj:
                self._update_indexes_for_record(None, old_obj)
        finally:
            try:
                lock.release()
            except:
                pass
        
        # Delete lock file after releasing lock
        try:
            lock_path.unlink(missing_ok=True)
        except:
            pass
    
    def atomic_update(self, record_id: int, transform_fn: Callable[[T], T]) -> Optional[T]:
        """
        Atomically update record using transform function.
        
        Args:
            record_id: ID to update
            transform_fn: Function that modifies the object
            
        Returns:
            Updated object or None if not found
        """
        obj = self.load(record_id)
        if obj is None:
            return None
        
        obj = transform_fn(obj)
        return self.save(obj)
    
    def register_index(self, field_name: str):
        """
        Register a field for indexing.
        
        Args:
            field_name: Field to index (use 'field1_field2' for composite)
        """
        index_path = self._get_index_path(field_name)
        self.indexes[field_name] = index_path
        
        # Create index file if it doesn't exist
        if not index_path.exists():
            self._write_pickle_atomic(index_path, {})
    
    def _load_index(self, field_name: str) -> Dict[Any, Set[int]]:
        """Load index file."""
        index_path = self._get_index_path(field_name)
        if not index_path.exists():
            return {}
        
        try:
            return self._read_pickle(index_path)
        except:
            return {}
    
    def _save_index(self, field_name: str, index_data: Dict[Any, Set[int]]):
        """Save index file."""
        index_path = self._get_index_path(field_name)
        lock_path = self.base_path / f"index_{field_name}.lock"
        lock = self._acquire_lock(lock_path)
        
        try:
            self._write_pickle_atomic(index_path, index_data)
        finally:
            lock.release()
    
    def _get_index_value(self, obj: Any, field_name: str) -> Any:
        """Extract index value from object (handles composite keys with __ delimiter)."""
        if obj is None:
            return None
        
        # Composite index uses '__' as delimiter (not '_' to avoid conflicts with field names like torrent_hash)
        if '__' in field_name:
            # Composite index
            parts = field_name.split('__')
            values = []
            for part in parts:
                if hasattr(obj, part):
                    values.append(getattr(obj, part))
            return tuple(values) if len(values) == len(parts) else None
        else:
            return getattr(obj, field_name, None)
    
    def _update_indexes_for_record(self, new_obj: Optional[T], old_obj: Optional[T]):
        """Update all indexes for a record change."""
        # Skip if no indexes registered
        if not self.indexes or len(self.indexes) == 0:
            return
        
        for field_name in self.indexes.keys():
            index_data = self._load_index(field_name)
            
            # Remove old index entry
            if old_obj is not None:
                old_value = self._get_index_value(old_obj, field_name)
                if old_value is not None and old_value in index_data:
                    index_data[old_value].discard(old_obj.id)
                    if not index_data[old_value]:
                        del index_data[old_value]
            
            # Add new index entry
            if new_obj is not None:
                new_value = self._get_index_value(new_obj, field_name)
                if new_value is not None:
                    if new_value not in index_data:
                        index_data[new_value] = set()
                    index_data[new_value].add(new_obj.id)
            
            self._save_index(field_name, index_data)
    
    def find_by_index(self, field_name: str, value: Any) -> Optional[T]:
        """
        Find first record matching index value.
        
        Args:
            field_name: Indexed field name
            value: Value to match
            
        Returns:
            First matching record or None
        """
        ids = self.get_ids_by_index(field_name, value)
        if ids:
            return self.load(list(ids)[0])
        return None
    
    def list_by_index(self, field_name: str, value: Any) -> List[T]:
        """
        List all records matching index value.
        
        Args:
            field_name: Indexed field name
            value: Value to match
            
        Returns:
            List of matching records
        """
        ids = self.get_ids_by_index(field_name, value)
        records = []
        for record_id in ids:
            obj = self.load(record_id)
            if obj:
                records.append(obj)
        return records
    
    def get_ids_by_index(self, field_name: str, value: Any) -> Set[int]:
        """
        Get record IDs matching index value.
        
        Args:
            field_name: Indexed field name
            value: Value to match
            
        Returns:
            Set of matching record IDs
        """
        index_data = self._load_index(field_name)
        return index_data.get(value, set()).copy()
    
    def get_ids_by_index_multi(self, field_name: str, values: List[Any]) -> Set[int]:
        """
        Get record IDs matching any of multiple index values.
        
        Args:
            field_name: Indexed field name
            values: List of values to match
            
        Returns:
            Set of matching record IDs
        """
        index_data = self._load_index(field_name)
        result = set()
        for value in values:
            result.update(index_data.get(value, set()))
        return result
    
    def list_all(self) -> List[T]:
        """
        Load all records in store.
        
        Returns:
            List of all records
        """
        records = []
        for file_path in self.base_path.glob("*.pkl"):
            if file_path.stem.isdigit():
                record_id = int(file_path.stem)
                obj = self.load(record_id)
                if obj:
                    records.append(obj)
        return records
    
    def rebuild_indexes(self):
        """Rebuild all index files by scanning all records."""
        print_warning(f"Rebuilding indexes for {self.store_name}...", prefix="PICKLE")
        
        # Clear all indexes
        for field_name in self.indexes.keys():
            self._save_index(field_name, {})
        
        # Scan all records
        for obj in self.list_all():
            self._update_indexes_for_record(obj, None)
        
        print_warning(f"Rebuilt {len(self.indexes)} indexes for {self.store_name}", prefix="PICKLE")
    
    def validate_integrity(self) -> Dict[str, Any]:
        """
        Validate all pickle files can be loaded.
        
        Returns:
            Dict with validation results
        """
        results = {
            'total': 0,
            'valid': 0,
            'errors': [],
            'missing_fields_filled': 0
        }
        
        for file_path in self.base_path.glob("*.pkl"):
            if not file_path.stem.isdigit():
                continue
            
            results['total'] += 1
            record_id = int(file_path.stem)
            
            try:
                obj = self.load(record_id)
                if obj:
                    results['valid'] += 1
                else:
                    results['errors'].append(f"Failed to load {record_id}")
            except Exception as e:
                results['errors'].append(f"Error loading {record_id}: {e}")
        
        return results
    
    @staticmethod
    def initialize_directories(store_names: List[str]):
        """
        Initialize directory structure for multiple stores.
        Supports paths with directory prefixes (e.g., 'data/downloads', 'cache/tmdb_cache').
        
        Args:
            store_names: List of store paths to create (e.g., ['data/downloads', 'cache/tmdb_cache'])
        """
        for store_name in store_names:
            store_path = Path(store_name)
            store_path.mkdir(parents=True, exist_ok=True)
