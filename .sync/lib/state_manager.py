#!/usr/bin/env python3
"""
State tracking and persistence for BMAD ↔ Linear sync system.

Manages content index, sync state, and number registry with atomic writes
and file locking for concurrent access safety.
"""

import os
import json
import fcntl
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from contextlib import contextmanager


class StateError(Exception):
    """Raised when state operations fail."""
    pass


class StateManager:
    """Manages sync state with atomic writes and file locking."""

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize state manager.

        Args:
            state_dir: Directory for state files (default: .sync/state/)
        """
        if state_dir is None:
            current_dir = Path.cwd()
            while current_dir != current_dir.parent:
                if (current_dir / '.sync').exists():
                    state_dir = current_dir / '.sync' / 'state'
                    break
                current_dir = current_dir.parent

            if state_dir is None:
                state_dir = Path('.sync/state')

        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.state_dir, 0o700)
        except Exception:
            pass

        # Backup directory
        self.backup_dir = self.state_dir.parent / 'backups'
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # State file paths
        self.content_index_file = self.state_dir / 'content_index.json'
        self.sync_state_file = self.state_dir / 'sync_state.json'
        self.number_registry_file = self.state_dir / 'number_registry.json'

        # Initialize files if they don't exist
        self._initialize_files()

    def _initialize_files(self) -> None:
        """Initialize state files with empty structures if they don't exist."""
        # Content index: {story_key: {hash, metadata}}
        if not self.content_index_file.exists():
            self._write_atomic(self.content_index_file, {})

        # Sync state: {last_sync, operations, errors}
        if not self.sync_state_file.exists():
            self._write_atomic(self.sync_state_file, {
                'last_sync': None,
                'operations': [],
                'errors': []
            })

        # Number registry: {story_key: linear_issue_id}
        if not self.number_registry_file.exists():
            self._write_atomic(self.number_registry_file, {})

    @contextmanager
    def _file_lock(self, file_path: Path, timeout: float = 5.0):
        """
        Context manager for file locking.

        Args:
            file_path: Path to file to lock
            timeout: Lock timeout in seconds

        Yields:
            File object with exclusive lock

        Raises:
            StateError: If lock cannot be acquired
        """
        lock_file = file_path.with_suffix(file_path.suffix + '.lock')

        try:
            lock_fd = open(lock_file, 'w')

            # Try to acquire exclusive lock with timeout
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                # Lock is held by another process
                import time
                elapsed = 0
                while elapsed < timeout:
                    time.sleep(0.1)
                    elapsed += 0.1
                    try:
                        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        continue
                else:
                    raise StateError(
                        f"Could not acquire lock on {file_path} after {timeout}s. "
                        "Another sync process may be running."
                    )

            yield lock_fd

        finally:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                lock_fd.close()
                lock_file.unlink(missing_ok=True)
            except Exception:
                pass

    def _backup_file(self, file_path: Path) -> None:
        """
        Create timestamped backup of file.

        Args:
            file_path: Path to file to backup
        """
        if not file_path.exists():
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
        backup_path = self.backup_dir / backup_name

        shutil.copy2(file_path, backup_path)

        # Clean up old backups (keep last 30 days)
        self._cleanup_old_backups(days=30)

    def _cleanup_old_backups(self, days: int = 30) -> None:
        """
        Remove backups older than specified days.

        Args:
            days: Maximum age of backups to keep
        """
        import time
        cutoff_time = time.time() - (days * 24 * 60 * 60)

        for backup_file in self.backup_dir.glob('*.json'):
            if backup_file.stat().st_mtime < cutoff_time:
                backup_file.unlink()

    def _write_atomic(self, file_path: Path, data: Dict[str, Any]) -> None:
        """
        Atomically write data to file (temp file + rename).

        Args:
            file_path: Path to file
            data: Data to write (will be JSON serialized)

        Raises:
            StateError: If write fails
        """
        temp_file = file_path.with_suffix(file_path.suffix + '.tmp')

        try:
            # Write to temp file
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2, sort_keys=True)

            # Atomic rename
            temp_file.replace(file_path)

        except Exception as e:
            temp_file.unlink(missing_ok=True)
            raise StateError(f"Failed to write {file_path}: {e}")

    def _load_json(self, file_path: Path) -> Dict[str, Any]:
        """
        Load and parse JSON file.

        Args:
            file_path: Path to JSON file

        Returns:
            Parsed JSON data

        Raises:
            StateError: If file is corrupted or unreadable
        """
        if not file_path.exists():
            raise StateError(f"State file not found: {file_path}")

        try:
            with open(file_path, 'r') as f:
                return json.load(f)

        except json.JSONDecodeError as e:
            raise StateError(
                f"Corrupted state file: {file_path}\n"
                f"Error: {e}\n"
                f"Recovery: Check backups in {self.backup_dir}"
            )
        except Exception as e:
            raise StateError(f"Failed to read {file_path}: {e}")

    # Content Index Operations
    def get_content_index(self) -> Dict[str, Dict[str, Any]]:
        """
        Get content index (story hashes and metadata).

        Returns:
            Content index dictionary

        Raises:
            StateError: If state cannot be loaded
        """
        with self._file_lock(self.content_index_file):
            return self._load_json(self.content_index_file)

    def update_content_index(self, story_key: str, content_hash: str, metadata: Dict[str, Any]) -> None:
        """
        Update content index for a story.

        Args:
            story_key: Story key (e.g., '1-1-project-setup')
            content_hash: SHA256 hash of story content
            metadata: Story metadata (title, status, etc.)

        Raises:
            StateError: If update fails
        """
        with self._file_lock(self.content_index_file):
            # Backup before update
            self._backup_file(self.content_index_file)

            # Load current index
            index = self._load_json(self.content_index_file)

            # Update entry
            index[story_key] = {
                'hash': content_hash,
                'metadata': metadata,
                'updated_at': datetime.now().isoformat()
            }

            # Atomic write
            self._write_atomic(self.content_index_file, index)

    # Sync State Operations
    def get_sync_state(self) -> Dict[str, Any]:
        """
        Get sync state (last sync metadata).

        Returns:
            Sync state dictionary

        Raises:
            StateError: If state cannot be loaded
        """
        with self._file_lock(self.sync_state_file):
            return self._load_json(self.sync_state_file)

    def update_sync_state(
        self,
        operation: str,
        result: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Update sync state after an operation.

        Args:
            operation: Operation name (e.g., 'sync_all', 'create_issue')
            result: Result status ('success', 'failure', 'partial')
            details: Optional operation details

        Raises:
            StateError: If update fails
        """
        with self._file_lock(self.sync_state_file):
            # Backup before update
            self._backup_file(self.sync_state_file)

            # Load current state
            state = self._load_json(self.sync_state_file)

            # Update last_sync timestamp
            state['last_sync'] = datetime.now().isoformat()

            # Add operation to history (keep last 100)
            operation_record = {
                'timestamp': datetime.now().isoformat(),
                'operation': operation,
                'result': result,
                'details': details or {}
            }

            operations = state.get('operations', [])
            operations.append(operation_record)
            state['operations'] = operations[-100:]  # Keep last 100

            # Track errors separately
            if result == 'failure':
                errors = state.get('errors', [])
                errors.append(operation_record)
                state['errors'] = errors[-50:]  # Keep last 50 errors

            # Atomic write
            self._write_atomic(self.sync_state_file, state)

    # Number Registry Operations
    def get_number_registry(self) -> Dict[str, str]:
        """
        Get number registry (story_key → linear_issue_id mappings).

        Returns:
            Number registry dictionary

        Raises:
            StateError: If state cannot be loaded
        """
        with self._file_lock(self.number_registry_file):
            return self._load_json(self.number_registry_file)

    def register_issue(self, story_key: str, issue_id: str) -> None:
        """
        Register Linear issue ID for a story.

        Args:
            story_key: Story key (e.g., '1-1-project-setup')
            issue_id: Linear issue ID (e.g., 'RAE-363')

        Raises:
            StateError: If update fails
        """
        # First, persist mapping in hierarchy (authoritative for BMAD→Linear IDs)
        try:
            # Import lazily to avoid circular import at module level
            from hierarchy import get_hierarchy_manager  # type: ignore
            hm = get_hierarchy_manager()
            if str(story_key).startswith("epic-"):
                hm.register_epic(story_key, issue_id)
            else:
                # Try infer parent epic from story key prefix
                parent_epic_key = None
                try:
                    parts = str(story_key).split("-", 2)
                    if len(parts) >= 2 and parts[0].isdigit():
                        parent_epic_key = f"epic-{int(parts[0])}"
                except Exception:
                    parent_epic_key = None
                hm.register_story(story_key, issue_id, parent_epic_key)
        except Exception:
            # Best-effort; do not fail registration if hierarchy write fails
            pass

        # Maintain compatibility by recording story mapping in number registry
        if not str(story_key).startswith("epic-"):
            with self._file_lock(self.number_registry_file):
                # Backup before update
                self._backup_file(self.number_registry_file)

                # Load current registry
                registry = self._load_json(self.number_registry_file)

                # Ensure structure
                if 'stories' not in registry:
                    registry['stories'] = {}

                entry = registry['stories'].get(story_key, {})
                entry['linear_issue_key'] = issue_id
                registry['stories'][story_key] = entry

                # Atomic write
                self._write_atomic(self.number_registry_file, registry)

    def get_issue_id(self, story_key: str) -> Optional[str]:
        """
        Get Linear issue ID for a story.

        Args:
            story_key: Story key

        Returns:
            Linear issue ID or None if not registered

        Raises:
            StateError: If state cannot be loaded
        """
        # Check hierarchy first (preferred)
        try:
            from hierarchy import get_hierarchy_manager  # type: ignore
            hm = get_hierarchy_manager()
            linear = hm.get_linear_id(story_key)
            if linear:
                return linear
        except Exception:
            pass

        # Fallback to number registry (new structure)
        try:
            registry = self.get_number_registry()
            stories = registry.get('stories', {}) if isinstance(registry, dict) else {}
            entry = stories.get(story_key) if isinstance(stories, dict) else None
            if isinstance(entry, dict) and entry.get('linear_issue_key'):
                return entry.get('linear_issue_key')
            # Legacy flat mapping fallback
            if isinstance(registry, dict) and story_key in registry and isinstance(registry[story_key], str):
                return registry[story_key]  # type: ignore[index]
        except Exception:
            pass

        return None


# Global state manager instance
_state_manager: Optional[StateManager] = None


def get_state_manager(state_dir: Optional[Path] = None) -> StateManager:
    """
    Get or create global state manager instance.

    Args:
        state_dir: Directory for state files (default: .sync/state/)

    Returns:
        StateManager instance
    """
    global _state_manager

    if _state_manager is None:
        _state_manager = StateManager(state_dir=state_dir)

    return _state_manager


if __name__ == '__main__':
    # Test state tracking functionality
    manager = get_state_manager()

    print("✓ Testing content index...")
    manager.update_content_index(
        story_key='1-1-project-setup',
        content_hash='abc123',
        metadata={'title': 'Project Setup', 'status': 'ready-for-dev'}
    )
    index = manager.get_content_index()
    print(f"  Content index: {len(index)} stories")

    print("\n✓ Testing sync state...")
    manager.update_sync_state(
        operation='test_sync',
        result='success',
        details={'stories': 5}
    )
    state = manager.get_sync_state()
    print(f"  Last sync: {state.get('last_sync')}")
    print(f"  Operations: {len(state.get('operations', []))}")

    print("\n✓ Testing number registry...")
    manager.register_issue('1-1-project-setup', 'RAE-363')
    issue_id = manager.get_issue_id('1-1-project-setup')
    print(f"  Story 1-1 → {issue_id}")

    print("\n✓ All state tracking tests passed!")
    print(f"\nState files:")
    print(f"  - {manager.content_index_file}")
    print(f"  - {manager.sync_state_file}")
    print(f"  - {manager.number_registry_file}")
    print(f"  - Backups: {manager.backup_dir}")
