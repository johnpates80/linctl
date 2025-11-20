#!/usr/bin/env python3
"""
Story numbering system for BMAD ↔ Linear synchronization.

Extends epic_numbering.py with comprehensive story number management:
- RAE-XXX assignment for stories within epic ranges
- Conflict detection via Linear API
- Renumbering support for insertions/deletions
- Multi-project configuration
- Historical tracking for traceability
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass

from linctl_wrapper import get_wrapper, LinctlError
from logger import get_logger


@dataclass
class StoryNumberAssignment:
    """Represents a story number assignment."""

    story_key: str  # e.g., "3-2-story-content-generation"
    linear_number: int  # e.g., 382 (for RAE-382)
    epic_number: int
    story_number: int  # Story within epic (1, 2, 3...)
    assigned_at: str
    linear_issue_key: Optional[str] = None  # e.g., "RAE-382"
    linear_uuid: Optional[str] = None
    conflict_resolved: bool = False
    previous_number: Optional[int] = None  # For renumbering history


@dataclass
class NumberConflict:
    """Represents a detected number conflict."""

    number: int
    story_key: str
    conflict_type: str  # 'linear_exists', 'already_assigned', 'out_of_range'
    details: str
    detected_at: str
    resolved: bool = False
    resolution: Optional[str] = None


class StoryNumberingSystem:
    """
    Manages comprehensive story number allocation with conflict detection.

    Integrates with:
    - EpicNumberingSystem for epic ranges
    - LinctlWrapper for Linear conflict detection
    - Registry for persistent tracking and history
    """

    def __init__(
        self,
        team_prefix: str = "RAE",
        epic_base: int = 360,
        block_size: int = 20,
        registry_path: Optional[Path] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize story numbering system.

        Args:
            team_prefix: Linear team prefix (e.g., RAE, PROP)
            epic_base: Base number for first epic (default: 360)
            block_size: Numbers reserved per epic (default: 20)
            registry_path: Path to number registry (default: .sync/state/number_registry.json)
            config: Optional configuration dict
        """
        self.team_prefix = team_prefix
        self.epic_base = epic_base
        self.block_size = block_size

        if registry_path is None:
            registry_path = Path('.sync/state/number_registry.json')
        self.registry_path = Path(registry_path)

        # Initialize epic numbering system directly (avoid singleton issues)
        from epic_numbering import EpicNumberingSystem
        self.epic_system = EpicNumberingSystem(
            epic_base=epic_base,
            block_size=block_size,
            registry_path=registry_path
        )

        # Initialize linctl wrapper for conflict detection
        self.linctl = get_wrapper()
        self.logger = get_logger()

        self._registry: Dict[str, Any] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        """Load registry or create new one."""
        if self.registry_path.exists():
            try:
                self._registry = json.loads(
                    self.registry_path.read_text(encoding='utf-8')
                )
                # Ensure story sections exist
                if 'stories' not in self._registry:
                    self._registry['stories'] = {}
                if 'conflicts' not in self._registry:
                    self._registry['conflicts'] = []
                if 'renumbering_history' not in self._registry:
                    self._registry['renumbering_history'] = []
            except (json.JSONDecodeError, IOError):
                self._registry = self._create_empty_registry()
        else:
            self._registry = self._create_empty_registry()

    def _create_empty_registry(self) -> Dict[str, Any]:
        """Create new empty registry structure."""
        return {
            "version": "1.0",
            "team_prefix": self.team_prefix,
            "epic_base": self.epic_base,
            "block_size": self.block_size,
            "epics": {},
            "stories": {},
            "conflicts": [],
            "renumbering_history": [],
            "reserved_ranges": [],
            "created": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def _save_registry(self) -> None:
        """Atomically save registry to disk."""
        self._registry["last_updated"] = datetime.now(timezone.utc).isoformat()

        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write via temp file
        tmp = self.registry_path.with_suffix('.tmp')
        tmp.write_text(
            json.dumps(self._registry, indent=2, sort_keys=True),
            encoding='utf-8'
        )
        tmp.replace(self.registry_path)

    def check_linear_conflict(self, number: int) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Check if a number exists in Linear.

        Args:
            number: Issue number to check (e.g., 382 for RAE-382)

        Returns:
            Tuple of (exists, issue_details)
        """
        issue_key = f"{self.team_prefix}-{number}"

        try:
            result = self.linctl.issue_get(issue_key)
            if result:
                return True, result
        except LinctlError:
            # Issue doesn't exist - this is expected for available numbers
            pass
        except Exception as e:
            self.logger.warning(
                f"Could not check Linear for {issue_key}",
                context={'error': str(e)}
            )

        return False, None

    def find_next_available_number(
        self,
        epic_number: int,
        preferred_story_number: Optional[int] = None
    ) -> Tuple[int, bool]:
        """
        Find next available number in epic range.

        Args:
            epic_number: Epic number (1, 2, 3, 4...)
            preferred_story_number: Preferred story position within epic

        Returns:
            Tuple of (available_number, is_preferred)
        """
        # Get epic range
        epic_range = self.epic_system.calculate_epic_range(epic_number)

        # If preferred story number specified, try it first
        if preferred_story_number is not None:
            preferred_num = epic_range.base_number + preferred_story_number
            if epic_range.contains(preferred_num):
                if not self._is_number_assigned(preferred_num):
                    exists, _ = self.check_linear_conflict(preferred_num)
                    if not exists:
                        return preferred_num, True

        # Scan range for first available
        for num in epic_range.available_numbers:
            if not self._is_number_assigned(num):
                exists, _ = self.check_linear_conflict(num)
                if not exists:
                    return num, False

        raise ValueError(
            f"No available numbers in Epic {epic_number} range "
            f"({epic_range.range_start}-{epic_range.range_end})"
        )

    def _is_number_assigned(self, number: int) -> bool:
        """Check if number already assigned in registry."""
        for assignment in self._registry.get('stories', {}).values():
            if assignment['linear_number'] == number:
                return True
        return False

    def assign_story_number(
        self,
        story_key: str,
        epic_number: int,
        story_number: int,
        preferred_number: Optional[int] = None
    ) -> StoryNumberAssignment:
        """
        Assign number to story with conflict detection.

        Args:
            story_key: Story identifier (e.g., "3-2-story-content-generation")
            epic_number: Epic number
            story_number: Story number within epic
            preferred_number: Optional preferred Linear number

        Returns:
            StoryNumberAssignment with assigned number

        Raises:
            ValueError: If assignment fails
        """
        # Check if already assigned
        if story_key in self._registry.get('stories', {}):
            existing = self._registry['stories'][story_key]
            self.logger.info(
                f"Story {story_key} already assigned to {self.team_prefix}-{existing['linear_number']}"
            )
            return StoryNumberAssignment(**existing)

        # Find available number
        try:
            if preferred_number:
                # Validate preferred number
                epic_range = self.epic_system.calculate_epic_range(epic_number)
                if not epic_range.contains(preferred_number):
                    self.logger.warning(
                        f"Preferred number {preferred_number} outside epic {epic_number} range"
                    )
                    preferred_number = None

            if preferred_number:
                # Check if preferred is available
                if self._is_number_assigned(preferred_number):
                    self._log_conflict(
                        number=preferred_number,
                        story_key=story_key,
                        conflict_type='already_assigned',
                        details=f"Preferred number {preferred_number} already assigned"
                    )
                    # Fall through to find next available
                    preferred_number = None
                else:
                    exists, details = self.check_linear_conflict(preferred_number)
                    if exists:
                        self._log_conflict(
                            number=preferred_number,
                            story_key=story_key,
                            conflict_type='linear_exists',
                            details=f"Number exists in Linear: {details.get('title', 'Unknown')}"
                        )
                        preferred_number = None
                    else:
                        assigned_number = preferred_number
                        is_preferred = True

            if preferred_number is None:
                # Find next available
                assigned_number, _ = self.find_next_available_number(
                    epic_number,
                    story_number
                )
                is_preferred = False

        except ValueError as e:
            self.logger.error(
                f"Failed to assign number for {story_key}",
                context={'error': str(e)}
            )
            raise

        # Create assignment
        assignment = StoryNumberAssignment(
            story_key=story_key,
            linear_number=assigned_number,
            epic_number=epic_number,
            story_number=story_number,
            assigned_at=datetime.now(timezone.utc).isoformat(),
            linear_issue_key=f"{self.team_prefix}-{assigned_number}",
            conflict_resolved=(not is_preferred and preferred_number is not None)
        )

        # Store in registry
        self._registry.setdefault('stories', {})[story_key] = {
            'story_key': assignment.story_key,
            'linear_number': assignment.linear_number,
            'epic_number': assignment.epic_number,
            'story_number': assignment.story_number,
            'assigned_at': assignment.assigned_at,
            'linear_issue_key': assignment.linear_issue_key,
            'conflict_resolved': assignment.conflict_resolved
        }

        self._save_registry()

        self.logger.info(
            f"Assigned {assignment.linear_issue_key} to {story_key}",
            context={
                'is_preferred': is_preferred,
                'conflict_resolved': assignment.conflict_resolved
            }
        )

        return assignment

    def _log_conflict(
        self,
        number: int,
        story_key: str,
        conflict_type: str,
        details: str
    ) -> NumberConflict:
        """Log a number conflict."""
        conflict = NumberConflict(
            number=number,
            story_key=story_key,
            conflict_type=conflict_type,
            details=details,
            detected_at=datetime.now(timezone.utc).isoformat()
        )

        conflict_dict = {
            'number': conflict.number,
            'story_key': conflict.story_key,
            'conflict_type': conflict.conflict_type,
            'details': conflict.details,
            'detected_at': conflict.detected_at,
            'resolved': conflict.resolved
        }

        self._registry.setdefault('conflicts', []).append(conflict_dict)

        self.logger.warning(
            f"Number conflict detected: {self.team_prefix}-{number}",
            context=conflict_dict
        )

        return conflict

    def get_story_assignment(self, story_key: str) -> Optional[StoryNumberAssignment]:
        """Get assignment for a story."""
        assignment_data = self._registry.get('stories', {}).get(story_key)
        if assignment_data:
            return StoryNumberAssignment(**assignment_data)
        return None

    def renumber_story(
        self,
        story_key: str,
        new_epic_number: int,
        new_story_number: int
    ) -> StoryNumberAssignment:
        """
        Renumber a story (for insertions/reorganization).

        Args:
            story_key: Story to renumber
            new_epic_number: New epic number
            new_story_number: New story number within epic

        Returns:
            New assignment
        """
        # Get existing assignment
        old_assignment = self.get_story_assignment(story_key)
        if not old_assignment:
            raise ValueError(f"Story {story_key} not found in registry")

        old_number = old_assignment.linear_number

        # Remove old assignment
        del self._registry['stories'][story_key]

        # Assign new number
        new_assignment = self.assign_story_number(
            story_key=story_key,
            epic_number=new_epic_number,
            story_number=new_story_number
        )

        new_assignment.previous_number = old_number

        # Log renumbering
        renumbering_entry = {
            'story_key': story_key,
            'old_number': old_number,
            'old_issue_key': f"{self.team_prefix}-{old_number}",
            'new_number': new_assignment.linear_number,
            'new_issue_key': new_assignment.linear_issue_key,
            'renumbered_at': datetime.now(timezone.utc).isoformat(),
            'reason': f"Moved from Epic {old_assignment.epic_number} to Epic {new_epic_number}"
        }

        self._registry.setdefault('renumbering_history', []).append(renumbering_entry)
        self._save_registry()

        self.logger.info(
            f"Renumbered {story_key}: {old_number} → {new_assignment.linear_number}",
            context=renumbering_entry
        )

        return new_assignment

    def list_story_assignments(self, epic_number: Optional[int] = None) -> List[StoryNumberAssignment]:
        """
        List all story assignments, optionally filtered by epic.

        Args:
            epic_number: Optional epic to filter by

        Returns:
            List of assignments
        """
        assignments = []
        for assignment_data in self._registry.get('stories', {}).values():
            if epic_number is None or assignment_data['epic_number'] == epic_number:
                assignments.append(StoryNumberAssignment(**assignment_data))

        return sorted(assignments, key=lambda a: (a.epic_number, a.story_number))

    def list_conflicts(self, unresolved_only: bool = True) -> List[NumberConflict]:
        """
        List number conflicts.

        Args:
            unresolved_only: Only return unresolved conflicts

        Returns:
            List of conflicts
        """
        conflicts = []
        for conflict_data in self._registry.get('conflicts', []):
            if unresolved_only and conflict_data.get('resolved', False):
                continue
            conflicts.append(NumberConflict(**conflict_data))

        return conflicts

    def get_renumbering_history(self, story_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get renumbering history.

        Args:
            story_key: Optional story to filter by

        Returns:
            List of renumbering entries
        """
        history = self._registry.get('renumbering_history', [])
        if story_key:
            history = [h for h in history if h['story_key'] == story_key]
        return history

    def get_registry_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        stories = self._registry.get('stories', {})
        conflicts = self._registry.get('conflicts', [])

        unresolved_conflicts = [c for c in conflicts if not c.get('resolved', False)]

        return {
            'team_prefix': self.team_prefix,
            'epic_base': self.epic_base,
            'block_size': self.block_size,
            'total_stories': len(stories),
            'total_conflicts': len(conflicts),
            'unresolved_conflicts': len(unresolved_conflicts),
            'renumbering_count': len(self._registry.get('renumbering_history', [])),
            'registry_path': str(self.registry_path),
            'last_updated': self._registry.get('last_updated')
        }


# Global instance
_story_numbering_system: Optional[StoryNumberingSystem] = None


def get_story_numbering_system(
    team_prefix: str = "RAE",
    epic_base: int = 360,
    block_size: int = 20,
    registry_path: Optional[Path] = None,
    config: Optional[Dict[str, Any]] = None
) -> StoryNumberingSystem:
    """
    Get or create global story numbering system.

    Args:
        team_prefix: Linear team prefix
        epic_base: Base number for first epic
        block_size: Numbers reserved per epic
        registry_path: Path to registry file
        config: Optional configuration

    Returns:
        StoryNumberingSystem instance
    """
    global _story_numbering_system

    if _story_numbering_system is None:
        _story_numbering_system = StoryNumberingSystem(
            team_prefix=team_prefix,
            epic_base=epic_base,
            block_size=block_size,
            registry_path=registry_path,
            config=config
        )

    return _story_numbering_system


if __name__ == '__main__':
    # Test the story numbering system
    system = get_story_numbering_system()

    print("Story Numbering System - Test")
    print("=" * 60)

    # Test assignment
    print("\n\nTest 1: Assign story numbers")
    print("-" * 60)

    test_stories = [
        ("3-1-epic-content-creation", 3, 1),
        ("3-2-story-content-generation", 3, 2),
        ("3-3-numbering-system-implementation", 3, 3),
    ]

    for story_key, epic_num, story_num in test_stories:
        try:
            assignment = system.assign_story_number(story_key, epic_num, story_num)
            print(f"✓ {story_key}: {assignment.linear_issue_key}")
        except Exception as e:
            print(f"✗ {story_key}: {e}")

    # Show stats
    print("\n\nRegistry Stats:")
    print("-" * 60)
    stats = system.get_registry_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # List assignments
    print("\n\nStory Assignments:")
    print("-" * 60)
    assignments = system.list_story_assignments()
    for assignment in assignments:
        print(f"  {assignment.linear_issue_key}: {assignment.story_key}")

    print("\n" + "=" * 60)
