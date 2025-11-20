#!/usr/bin/env python3
"""
Renumbering Engine for BMAD ↔ Linear Sync.

Handles structural changes that require renumbering of stories,
maintaining traceability and updating cross-references.

Implements Story 3.4 Task 3 requirements.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from content_parser import ContentParser
from state_manager import StateManager
from logger import get_logger


@dataclass
class RenumberMapping:
    """Represents a story renumbering operation."""
    old_key: str  # e.g., '1-2-story-name'
    new_key: str  # e.g., '1-3-story-name'
    old_epic: int
    old_story: int
    new_epic: int
    new_story: int
    linear_issue_id: Optional[str] = None
    reason: str = 'structural_change'
    timestamp: str = ''


class RenumberEngine:
    """Handles story renumbering and cascade updates."""

    def __init__(self, state_dir: Optional[Path] = None, docs_bmad: Optional[Path] = None):
        """
        Initialize renumber engine.

        Args:
            state_dir: Directory for state files
            docs_bmad: Path to docs-bmad directory
        """
        self.state = StateManager(state_dir=state_dir)
        self.parser = ContentParser()
        self.logger = get_logger()
        self.docs_bmad = Path(docs_bmad) if docs_bmad else Path('docs-bmad')

    def detect_renumbering(
        self,
        previous_index: Dict[str, Any],
        current_index: Dict[str, Any]
    ) -> List[RenumberMapping]:
        """
        Detect stories that have been renumbered.

        Args:
            previous_index: Previous content index
            current_index: Current content index

        Returns:
            List of RenumberMapping objects for renumbered stories
        """
        mappings: List[RenumberMapping] = []

        prev_stories = previous_index.get('stories', {})
        curr_stories = current_index.get('stories', {})

        for key, curr_meta in curr_stories.items():
            prev_meta = prev_stories.get(key)
            if not prev_meta:
                continue  # New story, not a renumber

            # Extract numbering
            curr_epic = curr_meta.get('epic_number') or curr_meta.get('epic')
            curr_story = curr_meta.get('story_number')
            prev_epic = prev_meta.get('epic_number') or prev_meta.get('epic')
            prev_story = prev_meta.get('story_number')

            if not all([curr_epic, curr_story, prev_epic, prev_story]):
                continue  # Missing numbering info

            # Check if renumbered
            if (curr_epic != prev_epic) or (curr_story != prev_story):
                # Construct old key (may differ from current key)
                old_key = f"{prev_epic}-{prev_story}-{key.split('-', 2)[-1]}"

                # Get Linear issue ID if registered
                issue_id = self.state.get_issue_id(key) or self.state.get_issue_id(old_key)

                mappings.append(RenumberMapping(
                    old_key=old_key,
                    new_key=key,
                    old_epic=int(prev_epic),
                    old_story=int(prev_story),
                    new_epic=int(curr_epic),
                    new_story=int(curr_story),
                    linear_issue_id=issue_id,
                    reason='structural_change',
                    timestamp=datetime.now().isoformat()
                ))

        return mappings

    def build_cascade_map(
        self,
        renumber_mappings: List[RenumberMapping],
        current_index: Dict[str, Any]
    ) -> Dict[str, List[str]]:
        """
        Build a map of epics to affected stories for cascade updates.

        Args:
            renumber_mappings: List of detected renumbering operations
            current_index: Current content index

        Returns:
            Dictionary mapping epic_key to list of affected story_keys
        """
        affected_by_epic: Dict[str, List[str]] = {}

        for mapping in renumber_mappings:
            epic_key = f'epic-{mapping.new_epic}'

            if epic_key not in affected_by_epic:
                affected_by_epic[epic_key] = []

            affected_by_epic[epic_key].append(mapping.new_key)

        return affected_by_epic

    def update_cross_references(
        self,
        mapping: RenumberMapping,
        docs_bmad: Path
    ) -> List[Tuple[Path, int]]:
        """
        Update cross-references in BMAD content files.

        Searches for references to the old story number and updates them.

        Args:
            mapping: RenumberMapping with old/new keys
            docs_bmad: Path to docs-bmad directory

        Returns:
            List of (file_path, num_changes) tuples
        """
        updated_files: List[Tuple[Path, int]] = []

        # Patterns to search for
        old_ref_patterns = [
            f"{mapping.old_epic}.{mapping.old_story}",  # "1.2"
            f"{mapping.old_epic}-{mapping.old_story}",  # "1-2"
            f"Story {mapping.old_epic}.{mapping.old_story}",  # "Story 1.2"
        ]

        new_ref_patterns = [
            f"{mapping.new_epic}.{mapping.new_story}",
            f"{mapping.new_epic}-{mapping.new_story}",
            f"Story {mapping.new_epic}.{mapping.new_story}",
        ]

        # Search in stories and epic files
        search_paths = [
            docs_bmad / 'stories',
            docs_bmad
        ]

        for search_path in search_paths:
            if not search_path.exists():
                continue

            for md_file in search_path.glob('**/*.md'):
                try:
                    content = md_file.read_text(encoding='utf-8')
                    updated_content = content
                    changes_made = 0

                    # Replace old references with new
                    for old_pattern, new_pattern in zip(old_ref_patterns, new_ref_patterns):
                        if old_pattern in updated_content:
                            updated_content = updated_content.replace(old_pattern, new_pattern)
                            changes_made += 1

                    if changes_made > 0:
                        # Write updated content
                        md_file.write_text(updated_content, encoding='utf-8')
                        updated_files.append((md_file, changes_made))

                        self.logger.info(
                            f"Updated {changes_made} references in {md_file.name}",
                            context={"old_key": mapping.old_key, "new_key": mapping.new_key}
                        )

                except Exception as e:
                    self.logger.error(
                        f"Failed to update references in {md_file}",
                        context={"error": str(e)}
                    )

        return updated_files

    def record_mapping(
        self,
        mapping: RenumberMapping
    ) -> None:
        """
        Record renumbering mapping in the number registry.

        Updates the registry to map both old and new keys to the Linear issue.

        Args:
            mapping: RenumberMapping to record
        """
        if not mapping.linear_issue_id:
            return

        # Register new mapping via StateManager (updates hierarchy and registry)
        try:
            self.state.register_issue(mapping.new_key, mapping.linear_issue_id)
        except Exception:
            # Non-fatal
            pass

        # Append renumbering history to number registry for traceability
        try:
            registry = self.state.get_number_registry() or {}
            if 'renumbering_history' not in registry:
                registry['renumbering_history'] = []
            registry['renumbering_history'].append({
                'old_key': mapping.old_key,
                'new_key': mapping.new_key,
                'issue_id': mapping.linear_issue_id,
                'timestamp': mapping.timestamp,
                'reason': mapping.reason
            })
            self.state._write_atomic(self.state.number_registry_file, registry)
        except Exception:
            # Ignore history write errors
            pass

        self.logger.info(
            f"Recorded renumbering: {mapping.old_key} → {mapping.new_key}",
            context={"issue_id": mapping.linear_issue_id}
        )

    def execute_renumbering(
        self,
        mappings: List[RenumberMapping],
        update_linear: bool = False
    ) -> Dict[str, Any]:
        """
        Execute renumbering cascade for all mappings.

        Args:
            mappings: List of RenumberMapping objects
            update_linear: Whether to update Linear issues (requires sync)

        Returns:
            Summary of renumbering operations
        """
        summary = {
            'timestamp': datetime.now().isoformat(),
            'total_renumbered': len(mappings),
            'cross_references_updated': 0,
            'files_updated': [],
            'mappings': [],
            'errors': []
        }

        for mapping in mappings:
            try:
                # Update cross-references in BMAD content
                updated_files = self.update_cross_references(mapping, self.docs_bmad)
                summary['cross_references_updated'] += sum(count for _, count in updated_files)
                summary['files_updated'].extend([str(path) for path, _ in updated_files])

                # Record mapping in registry
                self.record_mapping(mapping)

                # Add to summary
                summary['mappings'].append(asdict(mapping))

                self.logger.info(
                    f"Renumbering complete: {mapping.old_key} → {mapping.new_key}",
                    context={
                        "files_updated": len(updated_files),
                        "references_updated": sum(count for _, count in updated_files)
                    }
                )

            except Exception as e:
                error_msg = f"Failed to renumber {mapping.old_key}: {e}"
                summary['errors'].append(error_msg)
                self.logger.error(error_msg)

        # Note: Linear updates require sync engine integration
        if update_linear:
            summary['linear_update_note'] = (
                "Linear updates require sync engine integration. "
                "Run sync after renumbering to update Linear issues."
            )

        return summary

    def export_renumber_report(
        self,
        summary: Dict[str, Any],
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Export renumbering summary to a report file.

        Args:
            summary: Renumbering summary dictionary
            output_path: Optional output path

        Returns:
            Path to exported report
        """
        if not output_path:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = self.state.state_dir / f'renumber_report_{timestamp}.json'

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2), encoding='utf-8')

        self.logger.info(f"Renumber report saved: {output_path}")
        return output_path


def get_renumber_engine(
    state_dir: Optional[Path] = None,
    docs_bmad: Optional[Path] = None
) -> RenumberEngine:
    """
    Get RenumberEngine instance.

    Args:
        state_dir: Directory for state files
        docs_bmad: Path to docs-bmad directory

    Returns:
        RenumberEngine instance
    """
    return RenumberEngine(state_dir=state_dir, docs_bmad=docs_bmad)


if __name__ == '__main__':
    # Test renumbering engine
    engine = get_renumber_engine()

    # Example: Create a test mapping
    mapping = RenumberMapping(
        old_key='1-2-test-story',
        new_key='1-3-test-story',
        old_epic=1,
        old_story=2,
        new_epic=1,
        new_story=3,
        linear_issue_id='RAE-123',
        timestamp=datetime.now().isoformat()
    )

    print(f"✓ Created test mapping: {mapping.old_key} → {mapping.new_key}")
    print(f"  Linear issue: {mapping.linear_issue_id}")

    # Test recording (would update number_registry.json)
    # engine.record_mapping(mapping)
    # print("✓ Mapping recorded in number registry")
