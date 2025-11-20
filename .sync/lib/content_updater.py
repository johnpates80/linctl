#!/usr/bin/env python3
"""
Content Update and Change Detection for BMAD ↔ Linear Sync.

Provides field-level change detection and update type classification.
Implements Story 3.4 requirements for content updates and renumbering.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from content_parser import ContentParser
from state_manager import StateManager


@dataclass
class FieldChange:
    """Represents a change in a specific field."""
    field_name: str
    old_value: Optional[Any]
    new_value: Optional[Any]
    change_type: str  # 'added', 'modified', 'deleted'


@dataclass
class ContentUpdate:
    """Represents a content update with detailed change information."""
    content_key: str
    content_type: str  # 'story' | 'epic'
    update_type: str  # 'content_only', 'metadata_update', 'structural_update', 'renumbering_required'
    field_changes: List[FieldChange]
    previous_hash: str
    current_hash: str
    requires_renumbering: bool = False
    affected_stories: List[str] = None  # For structural changes


class ContentUpdater:
    """Handles content update detection and change analysis."""

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize content updater.

        Args:
            state_dir: Directory for state files (default: .sync/state/)
        """
        self.state = StateManager(state_dir=state_dir)
        self.parser = ContentParser()

    def compare_fields(
        self,
        previous_meta: Dict[str, Any],
        current_meta: Dict[str, Any],
        fields_to_check: List[str]
    ) -> List[FieldChange]:
        """
        Compare specific fields between previous and current metadata.

        Args:
            previous_meta: Previous metadata dictionary
            current_meta: Current metadata dictionary
            fields_to_check: List of field names to compare

        Returns:
            List of FieldChange objects for changed fields
        """
        changes: List[FieldChange] = []

        for field in fields_to_check:
            old_val = previous_meta.get(field)
            new_val = current_meta.get(field)

            if old_val != new_val:
                if old_val is None:
                    change_type = 'added'
                elif new_val is None:
                    change_type = 'deleted'
                else:
                    change_type = 'modified'

                changes.append(FieldChange(
                    field_name=field,
                    old_value=old_val,
                    new_value=new_val,
                    change_type=change_type
                ))

        return changes

    def determine_update_type(
        self,
        content_key: str,
        field_changes: List[FieldChange],
        content_type: str = 'story'
    ) -> Tuple[str, bool]:
        """
        Determine the type of update based on field changes.

        Args:
            content_key: Content identifier (e.g., '1-2-story-name')
            field_changes: List of detected field changes
            content_type: Type of content ('story' or 'epic')

        Returns:
            Tuple of (update_type, requires_renumbering)

        Update types:
            - content_only: Title, description, acceptance_criteria changed
            - metadata_update: Labels, priority, assignee changed
            - structural_update: Epic number changed, story moved
            - renumbering_required: Structural change that affects numbering
        """
        structural_fields = {'epic', 'epic_number', 'story_number', 'parent_epic'}
        metadata_fields = {'labels', 'priority', 'assignee', 'status'}
        content_fields = {'title', 'description', 'acceptance_criteria', 'tasks'}

        changed_fields = {fc.field_name for fc in field_changes}

        # Check for structural changes
        if changed_fields & structural_fields:
            # Structural changes require renumbering
            return ('structural_update', True)

        # Check for metadata-only changes
        if changed_fields <= metadata_fields:
            return ('metadata_update', False)

        # Otherwise, content changes
        return ('content_only', False)

    def detect_changes(
        self,
        content_key: str,
        previous_meta: Dict[str, Any],
        current_meta: Dict[str, Any],
        content_type: str = 'story'
    ) -> Optional[ContentUpdate]:
        """
        Detect and classify changes between previous and current content.

        Args:
            content_key: Content identifier
            previous_meta: Previous metadata from index
            current_meta: Current metadata from index
            content_type: Type of content ('story' or 'epic')

        Returns:
            ContentUpdate object if changes detected, None otherwise
        """
        # Check hashes first (quick check)
        prev_hash = previous_meta.get('hash', '')
        curr_hash = current_meta.get('hash', '')

        if prev_hash == curr_hash:
            return None  # No changes

        # Determine which fields to check based on content type
        if content_type == 'story':
            fields_to_check = [
                'title', 'description', 'status', 'epic', 'story_number',
                'epic_number', 'labels', 'priority', 'assignee',
                'acceptance_criteria', 'tasks'
            ]
        else:  # epic
            fields_to_check = [
                'title', 'description', 'status', 'epic_number'
            ]

        # Compare fields
        field_changes = self.compare_fields(previous_meta, current_meta, fields_to_check)

        if not field_changes:
            # Hash changed but no field changes detected
            # Possibly formatting or Dev Notes changes (not synced to Linear)
            return None

        # Determine update type and renumbering requirement
        update_type, requires_renumbering = self.determine_update_type(
            content_key, field_changes, content_type
        )

        return ContentUpdate(
            content_key=content_key,
            content_type=content_type,
            update_type=update_type,
            field_changes=field_changes,
            previous_hash=prev_hash,
            current_hash=curr_hash,
            requires_renumbering=requires_renumbering,
            affected_stories=[]  # Will be populated by renumbering logic
        )

    def analyze_all_changes(
        self,
        previous_index: Dict[str, Any],
        current_index: Dict[str, Any]
    ) -> List[ContentUpdate]:
        """
        Analyze all changes between previous and current index.

        Args:
            previous_index: Previous content index
            current_index: Current content index

        Returns:
            List of ContentUpdate objects for all detected changes
        """
        updates: List[ContentUpdate] = []

        # Analyze story changes
        prev_stories = previous_index.get('stories', {})
        curr_stories = current_index.get('stories', {})

        for key, curr_meta in curr_stories.items():
            prev_meta = prev_stories.get(key)
            if prev_meta:
                # Existing story - check for changes
                update = self.detect_changes(key, prev_meta, curr_meta, 'story')
                if update:
                    updates.append(update)

        # Analyze epic changes
        prev_epics = previous_index.get('epics', {})
        curr_epics = current_index.get('epics', {})

        for key, curr_meta in curr_epics.items():
            prev_meta = prev_epics.get(key)
            if prev_meta:
                # Existing epic - check for changes
                update = self.detect_changes(key, prev_meta, curr_meta, 'epic')
                if update:
                    updates.append(update)

        return updates

    def identify_renumbering_candidates(
        self,
        previous_index: Dict[str, Any],
        current_index: Dict[str, Any]
    ) -> Dict[str, List[str]]:
        """
        Identify stories that need renumbering due to structural changes.

        Args:
            previous_index: Previous content index
            current_index: Current content index

        Returns:
            Dictionary mapping epic_key to list of affected story_keys
        """
        affected_by_epic: Dict[str, List[str]] = {}

        prev_stories = previous_index.get('stories', {})
        curr_stories = current_index.get('stories', {})

        # Group stories by epic
        for key, curr_meta in curr_stories.items():
            epic_num = curr_meta.get('epic_number') or curr_meta.get('epic')
            if not epic_num:
                continue

            epic_key = f'epic-{epic_num}'

            # Check if story number changed
            prev_meta = prev_stories.get(key)
            if prev_meta:
                prev_story_num = prev_meta.get('story_number')
                curr_story_num = curr_meta.get('story_number')

                if prev_story_num != curr_story_num:
                    # Renumbering detected
                    if epic_key not in affected_by_epic:
                        affected_by_epic[epic_key] = []
                    affected_by_epic[epic_key].append(key)

        return affected_by_epic

    def export_change_summary(
        self,
        updates: List[ContentUpdate],
        output_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Export a human-readable summary of changes.

        Args:
            updates: List of ContentUpdate objects
            output_path: Optional path to write JSON summary

        Returns:
            Summary dictionary
        """
        summary = {
            'timestamp': datetime.now().isoformat(),
            'total_updates': len(updates),
            'by_type': {
                'content_only': 0,
                'metadata_update': 0,
                'structural_update': 0,
                'renumbering_required': 0
            },
            'updates': []
        }

        for update in updates:
            summary['by_type'][update.update_type] += 1
            if update.requires_renumbering:
                summary['by_type']['renumbering_required'] += 1

            summary['updates'].append({
                'content_key': update.content_key,
                'content_type': update.content_type,
                'update_type': update.update_type,
                'requires_renumbering': update.requires_renumbering,
                'changed_fields': [
                    {
                        'field': fc.field_name,
                        'change_type': fc.change_type,
                        'old_value': str(fc.old_value)[:100] if fc.old_value else None,
                        'new_value': str(fc.new_value)[:100] if fc.new_value else None
                    }
                    for fc in update.field_changes
                ]
            })

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(summary, indent=2), encoding='utf-8')

        return summary


def get_content_updater(state_dir: Optional[Path] = None) -> ContentUpdater:
    """
    Get ContentUpdater instance.

    Args:
        state_dir: Directory for state files

    Returns:
        ContentUpdater instance
    """
    return ContentUpdater(state_dir=state_dir)


if __name__ == '__main__':
    # Test content updater functionality
    updater = get_content_updater()

    # Example: Compare two versions of metadata
    previous = {
        'hash': 'abc123',
        'title': 'Old Title',
        'status': 'drafted',
        'epic_number': '1',
        'story_number': '2'
    }

    current = {
        'hash': 'def456',
        'title': 'New Title',
        'status': 'ready-for-dev',
        'epic_number': '1',
        'story_number': '3'  # Story renumbered!
    }

    update = updater.detect_changes('1-2-test', previous, current, 'story')

    if update:
        print(f"✓ Detected update for {update.content_key}")
        print(f"  Type: {update.update_type}")
        print(f"  Requires renumbering: {update.requires_renumbering}")
        print(f"  Changed fields: {len(update.field_changes)}")
        for fc in update.field_changes:
            print(f"    - {fc.field_name}: {fc.old_value} → {fc.new_value} ({fc.change_type})")
    else:
        print("No changes detected")
