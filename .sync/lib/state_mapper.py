#!/usr/bin/env python3
"""
State mapping and conversion between BMAD and Linear states.

Provides bidirectional state mapping, validation, and history tracking
for BMAD ↔ Linear synchronization.
"""

import os
import json
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from logger import get_logger


class StateMappingError(Exception):
    """Raised when state mapping operations fail."""
    pass


class StateValidationError(Exception):
    """Raised when state validation fails."""
    pass


@dataclass
class StateChange:
    """Represents a state transition event."""
    content_key: str
    from_state: str
    to_state: str
    timestamp: str
    source: str  # 'bmad' or 'linear'
    operation: str  # Operation that triggered the change
    user: Optional[str] = None
    content_type: str = 'story'  # 'story' or 'epic'


@dataclass
class StateConflict:
    """Represents a state synchronization conflict."""
    conflict_id: str
    content_key: str
    conflict_type: str  # 'state_mismatch', 'invalid_transition', etc.
    bmad_state: str
    bmad_updated: str
    linear_state: str
    linear_updated: str
    detected_at: str


class StateMapper:
    """Manages state mapping, validation, and history."""

    def __init__(self, config_dir: Optional[Path] = None, state_dir: Optional[Path] = None):
        """
        Initialize state mapper.

        Args:
            config_dir: Directory for configuration files (default: .sync/config/)
            state_dir: Directory for state files (default: .sync/state/)
        """
        # Find sync root
        sync_root = self._find_sync_root()

        if config_dir is None:
            config_dir = sync_root / 'config'
        if state_dir is None:
            state_dir = sync_root / 'state'

        self.config_dir = Path(config_dir)
        self.state_dir = Path(state_dir)

        # Ensure directories exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Conflicts directory
        self.conflicts_dir = sync_root / 'conflicts'
        self.conflicts_dir.mkdir(parents=True, exist_ok=True)

        # Load configuration
        self.config = self._load_config()
        self.logger = get_logger()

        # Initialize state history
        self.history_file = self.state_dir / 'state_history.json'
        self._initialize_history()

        # Initialize conflicts file
        self.conflicts_file = self.conflicts_dir / 'pending.json'
        self._initialize_conflicts()

    def _find_sync_root(self) -> Path:
        """Find .sync directory by walking up from current directory."""
        current = Path.cwd()
        while current != current.parent:
            sync_dir = current / '.sync'
            if sync_dir.exists():
                return sync_dir
            current = current.parent

        # Default to .sync in current directory
        return Path('.sync')

    def _load_config(self) -> Dict[str, Any]:
        """
        Load state mapping configuration.

        Returns:
            Configuration dictionary

        Raises:
            StateMappingError: If configuration cannot be loaded
        """
        config_file = self.config_dir / 'state_mapping.yaml'
        local_config_file = self.config_dir / 'state_mapping.local.yaml'

        try:
            # Load base configuration
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)

            # Merge local overrides if they exist
            if local_config_file.exists():
                with open(local_config_file, 'r') as f:
                    local_config = yaml.safe_load(f)

                # Deep merge local config
                config = self._merge_configs(config, local_config)

            return config

        except FileNotFoundError:
            raise StateMappingError(
                f"State mapping configuration not found: {config_file}\n"
                "Run 'bmad-sync init' to create default configuration."
            )
        except yaml.YAMLError as e:
            raise StateMappingError(f"Invalid YAML in configuration: {e}")
        except Exception as e:
            raise StateMappingError(f"Failed to load configuration: {e}")

    def _merge_configs(self, base: Dict, override: Dict) -> Dict:
        """Deep merge two configuration dictionaries."""
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value

        return result

    def _initialize_history(self) -> None:
        """Initialize state history file if it doesn't exist."""
        if not self.history_file.exists():
            self._write_json(self.history_file, {})

    def _initialize_conflicts(self) -> None:
        """Initialize conflicts file if it doesn't exist."""
        if not self.conflicts_file.exists():
            self._write_json(self.conflicts_file, [])

    def _write_json(self, file_path: Path, data: Any) -> None:
        """Write JSON data to file with proper formatting."""
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)

    def _read_json(self, file_path: Path) -> Any:
        """Read JSON data from file."""
        if not file_path.exists():
            return {} if 'history' in file_path.name else []

        with open(file_path, 'r') as f:
            return json.load(f)

    # State Conversion Functions

    def bmad_to_linear(self, bmad_state: str, content_type: str = 'story') -> str:
        """
        Convert BMAD state to Linear state.

        Args:
            bmad_state: BMAD state (e.g., 'in-progress')
            content_type: Content type ('story' or 'epic')

        Returns:
            Linear state (e.g., 'In Progress')

        Raises:
            StateMappingError: If state cannot be mapped
        """
        if not bmad_state:
            return "Backlog"  # Default for empty/null states

        # Get mapping configuration
        content_states = self.config.get(f'{content_type}_states', {})
        mapping = content_states.get('bmad_to_linear', {})

        # Look up state
        linear_state = mapping.get(bmad_state)

        if linear_state is None:
            # Unknown state - check strict mode
            if self.config.get('validation', {}).get('strict_mode', False):
                raise StateMappingError(f"Unknown BMAD state: {bmad_state}")

            # Warn and use default
            try:
                self.logger.warning("Unknown BMAD state '%s', defaulting to 'Backlog'", bmad_state)
            except Exception:
                pass
            return "Backlog"

        return linear_state

    def linear_to_bmad(
        self,
        linear_state: str,
        content_type: str = 'story',
        context_hints: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Convert Linear state to BMAD state.

        Args:
            linear_state: Linear state (e.g., 'In Progress')
            content_type: Content type ('story' or 'epic')
            context_hints: Optional context for ambiguous mappings
                          (e.g., {'has_context_file': True})

        Returns:
            BMAD state (e.g., 'in-progress')

        Raises:
            StateMappingError: If state cannot be mapped
        """
        if not linear_state:
            return "backlog"  # Default for empty/null states

        # Get mapping configuration
        content_states = self.config.get(f'{content_type}_states', {})
        mapping = content_states.get('linear_to_bmad', {})

        # Look up state
        bmad_state = mapping.get(linear_state)

        if bmad_state is None:
            # Unknown state - check strict mode
            if self.config.get('validation', {}).get('strict_mode', False):
                raise StateMappingError(f"Unknown Linear state: {linear_state}")

            # Warn and use default
            try:
                self.logger.warning("Unknown Linear state '%s', defaulting to 'backlog'", linear_state)
            except Exception:
                pass
            return "backlog"

        # Handle ambiguous mappings (e.g., "Todo" → "drafted" or "ready-for-dev")
        if linear_state == "Todo" and content_type == 'story':
            # Check context-aware logic
            context_config = self.config.get('context_aware_mapping', {})
            todo_logic = context_config.get('todo_to_bmad_logic', [])

            for rule in todo_logic:
                condition = rule.get('condition')
                result = rule.get('result')

                if condition == 'story_context_file_exists':
                    # Check if context file exists
                    if context_hints and context_hints.get('has_context_file'):
                        return result  # 'ready-for-dev'

                elif condition == 'default':
                    return result  # 'drafted'

        return bmad_state

    # State Validation

    def validate_transition(
        self,
        from_state: str,
        to_state: str,
        content_type: str = 'story'
    ) -> Tuple[bool, str]:
        """
        Validate a state transition.

        Args:
            from_state: Current state
            to_state: Target state
            content_type: Content type ('story' or 'epic')

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Get valid transitions
        valid_transitions = self.config.get('valid_transitions', {})

        # Check if transition is allowed
        allowed_targets = valid_transitions.get(from_state, [])

        if to_state not in allowed_targets:
            error_msg = (
                f"Invalid transition: {from_state} → {to_state}\n"
                f"Valid transitions from '{from_state}': {', '.join(allowed_targets)}"
            )
            return False, error_msg

        return True, ""

    def validate_transition_or_raise(
        self,
        from_state: str,
        to_state: str,
        content_type: str = 'story'
    ) -> None:
        """
        Validate a state transition and raise exception if invalid.

        Args:
            from_state: Current state
            to_state: Target state
            content_type: Content type

        Raises:
            StateValidationError: If transition is invalid
        """
        is_valid, error_msg = self.validate_transition(from_state, to_state, content_type)

        if not is_valid:
            raise StateValidationError(error_msg)

    # State History Tracking

    def log_state_change(
        self,
        content_key: str,
        from_state: str,
        to_state: str,
        source: str,
        operation: str,
        user: Optional[str] = None,
        content_type: str = 'story'
    ) -> None:
        """
        Log a state change to history.

        Args:
            content_key: Content key (e.g., '1-1-project-setup')
            from_state: Previous state
            to_state: New state
            source: Source system ('bmad' or 'linear')
            operation: Operation that triggered change
            user: Optional username
            content_type: Content type
        """
        # Create state change record
        change = StateChange(
            content_key=content_key,
            from_state=from_state,
            to_state=to_state,
            timestamp=datetime.now().isoformat(),
            source=source,
            operation=operation,
            user=user,
            content_type=content_type
        )

        # Load history
        history = self._read_json(self.history_file)

        # Add change to content's history
        if content_key not in history:
            history[content_key] = []

        history[content_key].append(asdict(change))

        # Write back
        self._write_json(self.history_file, history)

        # Apply retention policy
        self._apply_retention_policy()

    def get_state_history(self, content_key: str) -> List[Dict[str, Any]]:
        """
        Get state history for content.

        Args:
            content_key: Content key

        Returns:
            List of state changes (oldest to newest)
        """
        history = self._read_json(self.history_file)
        return history.get(content_key, [])

    def get_recent_changes(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get recent state changes across all content.

        Args:
            hours: Number of hours to look back

        Returns:
            List of state changes (newest first)
        """
        history = self._read_json(self.history_file)
        cutoff = datetime.now() - timedelta(hours=hours)

        recent = []
        for content_key, changes in history.items():
            for change in changes:
                change_time = datetime.fromisoformat(change['timestamp'])
                if change_time >= cutoff:
                    recent.append(change)

        # Sort by timestamp (newest first)
        recent.sort(key=lambda x: x['timestamp'], reverse=True)

        return recent

    def _apply_retention_policy(self) -> None:
        """Apply retention policy to state history."""
        retention_days = self.config.get('history', {}).get('retention_days', 90)
        cutoff = datetime.now() - timedelta(days=retention_days)

        history = self._read_json(self.history_file)
        modified = False

        for content_key, changes in list(history.items()):
            # Filter out old changes
            kept_changes = [
                change for change in changes
                if datetime.fromisoformat(change['timestamp']) >= cutoff
            ]

            if len(kept_changes) != len(changes):
                history[content_key] = kept_changes
                modified = True

            # Remove empty entries
            if not history[content_key]:
                del history[content_key]
                modified = True

        if modified:
            self._write_json(self.history_file, history)

    # Conflict Detection

    def detect_conflict(
        self,
        content_key: str,
        bmad_state: str,
        bmad_updated: str,
        linear_state: str,
        linear_updated: str,
        last_sync: Optional[str] = None
    ) -> Optional[StateConflict]:
        """
        Detect state synchronization conflict.

        Args:
            content_key: Content key
            bmad_state: Current BMAD state
            bmad_updated: BMAD last updated timestamp
            linear_state: Current Linear state
            linear_updated: Linear last updated timestamp
            last_sync: Last successful sync timestamp

        Returns:
            StateConflict if conflict detected, None otherwise
        """
        # Convert Linear state to BMAD for comparison
        linear_as_bmad = self.linear_to_bmad(linear_state)

        # If states match, no conflict
        if bmad_state == linear_as_bmad:
            return None

        # If we have last_sync, check if both changed since then
        if last_sync:
            # Handle ISO timestamps with 'Z' suffix
            bmad_time = datetime.fromisoformat(bmad_updated.replace('Z', '+00:00'))
            linear_time = datetime.fromisoformat(linear_updated.replace('Z', '+00:00'))
            sync_time = datetime.fromisoformat(last_sync.replace('Z', '+00:00'))

            # Both changed since last sync = conflict
            if bmad_time > sync_time and linear_time > sync_time:
                conflict_id = f"c-{content_key}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

                return StateConflict(
                    conflict_id=conflict_id,
                    content_key=content_key,
                    conflict_type='state_mismatch',
                    bmad_state=bmad_state,
                    bmad_updated=bmad_updated,
                    linear_state=linear_state,
                    linear_updated=linear_updated,
                    detected_at=datetime.now().isoformat()
                )

        return None

    def save_conflict(self, conflict: StateConflict) -> None:
        """
        Save a conflict for later resolution.

        Args:
            conflict: State conflict to save
        """
        conflicts = self._read_json(self.conflicts_file)
        conflicts.append(asdict(conflict))
        self._write_json(self.conflicts_file, conflicts)

    def get_pending_conflicts(self) -> List[StateConflict]:
        """
        Get all pending conflicts.

        Returns:
            List of unresolved conflicts
        """
        conflicts_data = self._read_json(self.conflicts_file)
        return [StateConflict(**c) for c in conflicts_data]

    def resolve_conflict(self, conflict_id: str) -> None:
        """
        Mark a conflict as resolved.

        Args:
            conflict_id: Conflict ID to resolve
        """
        conflicts = self._read_json(self.conflicts_file)
        conflicts = [c for c in conflicts if c['conflict_id'] != conflict_id]
        self._write_json(self.conflicts_file, conflicts)


# Global state mapper instance
_state_mapper: Optional[StateMapper] = None


def get_state_mapper(
    config_dir: Optional[Path] = None,
    state_dir: Optional[Path] = None
) -> StateMapper:
    """
    Get or create global state mapper instance.

    Args:
        config_dir: Configuration directory
        state_dir: State directory

    Returns:
        StateMapper instance
    """
    global _state_mapper

    if _state_mapper is None:
        _state_mapper = StateMapper(config_dir=config_dir, state_dir=state_dir)

    return _state_mapper


if __name__ == '__main__':
    # Test state mapping functionality
    mapper = get_state_mapper()

    print("✓ Testing BMAD → Linear conversion...")
    test_cases = [
        ('backlog', 'story'),
        ('drafted', 'story'),
        ('ready-for-dev', 'story'),
        ('in-progress', 'story'),
        ('review', 'story'),
        ('done', 'story'),
    ]

    for bmad_state, content_type in test_cases:
        linear_state = mapper.bmad_to_linear(bmad_state, content_type)
        print(f"  {bmad_state} → {linear_state}")

    print("\n✓ Testing Linear → BMAD conversion...")
    test_cases = [
        ('Backlog', 'story', {}),
        ('Todo', 'story', {}),
        ('Todo', 'story', {'has_context_file': True}),
        ('In Progress', 'story', {}),
        ('In Review', 'story', {}),
        ('Done', 'story', {}),
    ]

    for linear_state, content_type, context in test_cases:
        bmad_state = mapper.linear_to_bmad(linear_state, content_type, context)
        context_str = " (with context)" if context else ""
        print(f"  {linear_state}{context_str} → {bmad_state}")

    print("\n✓ Testing state validation...")
    test_transitions = [
        ('backlog', 'drafted', True),
        ('drafted', 'ready-for-dev', True),
        ('backlog', 'done', False),  # Invalid
        ('done', 'in-progress', True),  # Reopening allowed
    ]

    for from_state, to_state, expected_valid in test_transitions:
        is_valid, error = mapper.validate_transition(from_state, to_state)
        status = "✓" if is_valid == expected_valid else "✗"
        print(f"  {status} {from_state} → {to_state}: {is_valid}")

    print("\n✓ Testing state history...")
    mapper.log_state_change(
        content_key='1-1-project-setup',
        from_state='backlog',
        to_state='drafted',
        source='bmad',
        operation='create-story',
        user='john'
    )

    history = mapper.get_state_history('1-1-project-setup')
    print(f"  History entries: {len(history)}")

    print("\n✓ Testing conflict detection...")
    conflict = mapper.detect_conflict(
        content_key='1-2-content-discovery',
        bmad_state='in-progress',
        bmad_updated='2025-11-06T14:00:00Z',
        linear_state='Done',
        linear_updated='2025-11-06T15:00:00Z',
        last_sync='2025-11-06T13:00:00Z'
    )

    if conflict:
        print(f"  Conflict detected: {conflict.conflict_type}")
        mapper.save_conflict(conflict)
    else:
        print("  No conflict detected")

    print("\n✓ All state mapping tests passed!")
    print(f"\nState files:")
    print(f"  - Config: {mapper.config_dir / 'state_mapping.yaml'}")
    print(f"  - History: {mapper.history_file}")
    print(f"  - Conflicts: {mapper.conflicts_file}")
