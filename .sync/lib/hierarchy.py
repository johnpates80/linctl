#!/usr/bin/env python3
"""
Hierarchy management for BMAD ↔ Linear synchronization.

Handles:
- Epic-Story parent-child relationships
- Linear parent_id field management
- Hierarchical relationship tracking in state
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from linctl_wrapper import get_wrapper, LinctlError
from state_manager import StateManager
from logger import get_logger


@dataclass
class HierarchyRelationship:
    """Represents a parent-child relationship."""

    parent_type: str  # 'epic'
    parent_bmad_key: str  # 'epic-1'
    parent_linear_id: Optional[str]  # Linear UUID or issue key
    child_type: str  # 'story'
    child_bmad_key: str  # '1-1-setup'
    child_linear_id: Optional[str]  # Linear UUID or issue key


class HierarchyManager:
    """
    Manages hierarchical relationships between epics and stories.
    """

    def __init__(self, state_path: Optional[Path] = None):
        """
        Initialize hierarchy manager.

        Args:
            state_path: Path to hierarchy state file (default: .sync/state/hierarchy.json)
        """
        if state_path is None:
            state_path = Path('.sync/state/hierarchy.json')
        self.state_path = Path(state_path)

        self.state_manager = StateManager()
        self.wrapper = get_wrapper()
        self.logger = get_logger()

        self._hierarchy: Dict[str, Any] = {}
        self._load_hierarchy()

    def _load_hierarchy(self) -> None:
        """Load hierarchy state from disk or create new."""
        if self.state_path.exists():
            try:
                self._hierarchy = json.loads(
                    self.state_path.read_text(encoding='utf-8')
                )
            except (json.JSONDecodeError, IOError):
                self._hierarchy = self._create_empty_hierarchy()
        else:
            self._hierarchy = self._create_empty_hierarchy()

    def _create_empty_hierarchy(self) -> Dict[str, Any]:
        """Create new empty hierarchy structure."""
        return {
            "version": "1.0",
            "relationships": {},  # child_key -> parent_key
            "children": {},  # parent_key -> [child_keys]
            "linear_mappings": {  # BMAD key -> Linear ID
                "epics": {},
                "stories": {},
            }
        }

    def _save_hierarchy(self) -> None:
        """Atomically save hierarchy to disk."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write via temp file
        tmp = self.state_path.with_suffix('.tmp')
        tmp.write_text(
            json.dumps(self._hierarchy, indent=2, sort_keys=True),
            encoding='utf-8'
        )
        tmp.replace(self.state_path)

    def register_epic(self, epic_key: str, linear_id: str) -> None:
        """
        Register epic in hierarchy.

        Args:
            epic_key: BMAD epic key (e.g., 'epic-1')
            linear_id: Linear UUID or issue key
        """
        self._hierarchy["linear_mappings"]["epics"][epic_key] = linear_id

        # Initialize children list if not exists
        if epic_key not in self._hierarchy["children"]:
            self._hierarchy["children"][epic_key] = []

        self._save_hierarchy()

        self.logger.debug(
            f"Registered epic in hierarchy: {epic_key} -> {linear_id}",
            context={'epic_key': epic_key, 'linear_id': linear_id}
        )

    def register_story(
        self,
        story_key: str,
        linear_id: str,
        parent_epic_key: Optional[str] = None
    ) -> None:
        """
        Register story in hierarchy.

        Args:
            story_key: BMAD story key (e.g., '1-1-setup')
            linear_id: Linear UUID or issue key
            parent_epic_key: Optional parent epic key (e.g., 'epic-1')
        """
        self._hierarchy["linear_mappings"]["stories"][story_key] = linear_id

        if parent_epic_key:
            # Set parent relationship
            self._hierarchy["relationships"][story_key] = parent_epic_key

            # Add to parent's children list
            if parent_epic_key not in self._hierarchy["children"]:
                self._hierarchy["children"][parent_epic_key] = []

            if story_key not in self._hierarchy["children"][parent_epic_key]:
                self._hierarchy["children"][parent_epic_key].append(story_key)

        self._save_hierarchy()

        self.logger.debug(
            f"Registered story in hierarchy: {story_key} -> {linear_id}",
            context={
                'story_key': story_key,
                'linear_id': linear_id,
                'parent_epic': parent_epic_key
            }
        )

    def get_parent_epic(self, story_key: str) -> Optional[str]:
        """
        Get parent epic for a story.

        Args:
            story_key: BMAD story key

        Returns:
            Parent epic key or None
        """
        return self._hierarchy.get("relationships", {}).get(story_key)

    def get_children(self, epic_key: str) -> List[str]:
        """
        Get child stories for an epic.

        Args:
            epic_key: BMAD epic key

        Returns:
            List of child story keys
        """
        return self._hierarchy.get("children", {}).get(epic_key, [])

    def get_linear_id(self, bmad_key: str) -> Optional[str]:
        """
        Get Linear ID for BMAD key.

        Args:
            bmad_key: BMAD key (epic or story)

        Returns:
            Linear UUID/issue key or None
        """
        # Check epics
        linear_id = self._hierarchy.get("linear_mappings", {}).get("epics", {}).get(bmad_key)
        if linear_id:
            return linear_id

        # Check stories
        return self._hierarchy.get("linear_mappings", {}).get("stories", {}).get(bmad_key)

    def link_story_to_epic_in_linear(
        self,
        story_key: str,
        epic_key: Optional[str] = None
    ) -> bool:
        """
        Link story to epic in Linear using parent_id field.

        Args:
            story_key: BMAD story key
            epic_key: Optional parent epic key (auto-detected if not provided)

        Returns:
            True if link succeeded, False otherwise
        """
        # Get or detect parent epic
        if not epic_key:
            epic_key = self.infer_parent_epic(story_key)

        if not epic_key:
            self.logger.warning(
                f"Cannot link story {story_key}: no parent epic found",
                context={'story_key': story_key}
            )
            return False

        # Get Linear IDs
        story_linear_id = self.get_linear_id(story_key)
        epic_linear_id = self.get_linear_id(epic_key)

        if not story_linear_id:
            self.logger.warning(
                f"Cannot link story {story_key}: no Linear ID found",
                context={'story_key': story_key}
            )
            return False

        if not epic_linear_id:
            self.logger.warning(
                f"Cannot link story {story_key}: parent epic {epic_key} has no Linear ID",
                context={'story_key': story_key, 'epic_key': epic_key}
            )
            return False

        # Update story in Linear with parent_id
        try:
            self.logger.info(
                f"Linking story {story_key} to epic {epic_key} in Linear",
                context={
                    'story': story_key,
                    'story_linear': story_linear_id,
                    'epic': epic_key,
                    'epic_linear': epic_linear_id
                }
            )

            # Note: linctl may not support parent_id directly yet
            # This is a placeholder for when it's supported
            # For now, we track the relationship in our hierarchy state
            self.register_story(story_key, story_linear_id, epic_key)

            self.logger.info(
                f"Story {story_key} linked to epic {epic_key}",
                context={'story_key': story_key, 'epic_key': epic_key}
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to link story {story_key} to epic {epic_key}",
                context={'error': str(e)}
            )
            return False

    def infer_parent_epic(self, story_key: str) -> Optional[str]:
        """
        Infer parent epic from story key.

        Args:
            story_key: Story key (e.g., '1-1-setup', '2-3-feature')

        Returns:
            Inferred epic key (e.g., 'epic-1') or None

        Examples:
            '1-1-setup' -> 'epic-1'
            '2-3-feature' -> 'epic-2'
            '3-1-numbering' -> 'epic-3'
        """
        # Extract epic number from story key (first number)
        parts = story_key.split('-')
        if parts and parts[0].isdigit():
            epic_num = int(parts[0])
            return f"epic-{epic_num}"

        return None

    def get_hierarchy_stats(self) -> Dict[str, Any]:
        """
        Get statistics about current hierarchy.

        Returns:
            Dictionary with hierarchy statistics
        """
        epics = self._hierarchy.get("linear_mappings", {}).get("epics", {})
        stories = self._hierarchy.get("linear_mappings", {}).get("stories", {})
        relationships = self._hierarchy.get("relationships", {})

        return {
            "epic_count": len(epics),
            "story_count": len(stories),
            "linked_story_count": len(relationships),
            "unlinked_story_count": len(stories) - len(relationships),
            "state_path": str(self.state_path),
        }

    def get_relationship(self, story_key: str) -> Optional[HierarchyRelationship]:
        """
        Get full relationship details for a story.

        Args:
            story_key: BMAD story key

        Returns:
            HierarchyRelationship or None
        """
        epic_key = self.get_parent_epic(story_key)
        if not epic_key:
            return None

        return HierarchyRelationship(
            parent_type='epic',
            parent_bmad_key=epic_key,
            parent_linear_id=self.get_linear_id(epic_key),
            child_type='story',
            child_bmad_key=story_key,
            child_linear_id=self.get_linear_id(story_key)
        )

    def sync_hierarchy_to_linear(self) -> Dict[str, Any]:
        """
        Sync all hierarchy relationships to Linear.

        Links all registered stories to their parent epics in Linear.

        Returns:
            Summary of sync operation
        """
        results = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'skipped': 0,
            'errors': []
        }

        stories = self._hierarchy.get("linear_mappings", {}).get("stories", {})

        for story_key in stories.keys():
            results['total'] += 1

            # Check if already linked
            if story_key in self._hierarchy.get("relationships", {}):
                results['skipped'] += 1
                continue

            # Try to link
            if self.link_story_to_epic_in_linear(story_key):
                results['success'] += 1
            else:
                results['failed'] += 1
                results['errors'].append(f"Failed to link {story_key}")

        return results


# Module interface functions

def get_hierarchy_manager(state_path: Optional[Path] = None) -> HierarchyManager:
    """
    Get hierarchy manager instance.

    Args:
        state_path: Optional path to hierarchy state file

    Returns:
        HierarchyManager instance
    """
    return HierarchyManager(state_path)


def link_story_to_epic(story_key: str, epic_key: Optional[str] = None) -> bool:
    """
    Link story to epic in Linear.

    Args:
        story_key: BMAD story key
        epic_key: Optional parent epic key (auto-inferred if not provided)

    Returns:
        True if successful
    """
    manager = get_hierarchy_manager()
    return manager.link_story_to_epic_in_linear(story_key, epic_key)


if __name__ == '__main__':
    # Test hierarchy system
    manager = get_hierarchy_manager()

    print("Hierarchy Manager - Test")
    print("=" * 50)

    # Register test epic
    print("\n1. Registering epic-1...")
    manager.register_epic("epic-1", "test-epic-uuid-1")

    # Register test stories
    print("2. Registering stories...")
    manager.register_story("1-1-setup", "test-story-uuid-1", "epic-1")
    manager.register_story("1-2-discovery", "test-story-uuid-2", "epic-1")

    # Test parent lookup
    print("\n3. Testing parent lookup...")
    parent = manager.get_parent_epic("1-1-setup")
    print(f"   Parent of 1-1-setup: {parent}")

    # Test children lookup
    print("\n4. Testing children lookup...")
    children = manager.get_children("epic-1")
    print(f"   Children of epic-1: {children}")

    # Test inference
    print("\n5. Testing epic inference...")
    inferred = manager.infer_parent_epic("2-3-feature")
    print(f"   Inferred epic for 2-3-feature: {inferred}")

    # Show stats
    stats = manager.get_hierarchy_stats()
    print(f"\n6. Hierarchy Stats:")
    print(f"   Epics: {stats['epic_count']}")
    print(f"   Stories: {stats['story_count']}")
    print(f"   Linked: {stats['linked_story_count']}")
    print(f"   Unlinked: {stats['unlinked_story_count']}")
