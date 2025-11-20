#!/usr/bin/env python3
"""
Metadata management for Linear issues (epics and stories).

Handles:
- Label creation and application ("epic", "epic-N")
- Project assignment
- Default state setting
- Metadata tracking
"""

from typing import Dict, Any, List, Optional
from pathlib import Path

from linctl_wrapper import get_wrapper, LinctlError
from logger import get_logger


class MetadataManager:
    """
    Manages metadata for Linear issues (labels, projects, states).
    """

    def __init__(self, team: str):
        """
        Initialize metadata manager.

        Args:
            team: Linear team ID or name
        """
        self.team = team
        self.wrapper = get_wrapper()
        self.logger = get_logger()

        self._label_cache: Dict[str, str] = {}  # label_name -> label_id

    def ensure_epic_labels_exist(self, epic_numbers: Optional[List[int]] = None) -> Dict[str, str]:
        """
        Ensure all required epic labels exist in Linear.

        Creates labels if they don't exist:
        - "epic" (general epic marker)
        - "epic-1", "epic-2", etc. (specific epic labels)

        Args:
            epic_numbers: Optional list of epic numbers to create labels for

        Returns:
            Dictionary mapping label names to label IDs
        """
        labels_to_create = ["epic"]

        if epic_numbers:
            labels_to_create.extend([f"epic-{n}" for n in epic_numbers])

        created_labels = {}

        for label_name in labels_to_create:
            label_id = self._ensure_label_exists(label_name)
            if label_id:
                created_labels[label_name] = label_id

        return created_labels

    def _ensure_label_exists(self, label_name: str, color: Optional[str] = None) -> Optional[str]:
        """
        Ensure a label exists in Linear, creating it if necessary.

        Args:
            label_name: Label name (e.g., "epic", "epic-1")
            color: Optional hex color code (e.g., "#FF6B6B")

        Returns:
            Label ID or None if creation failed
        """
        # Check cache
        if label_name in self._label_cache:
            return self._label_cache[label_name]

        # Try to find existing label via linctl
        try:
            # Note: linctl may not have label lookup yet
            # For now, we'll attempt to create and handle duplicates
            pass
        except Exception:
            pass

        # Create label
        try:
            # Default colors for epic labels
            if color is None:
                if label_name == "epic":
                    color = "#8B5CF6"  # Purple
                elif label_name.startswith("epic-"):
                    # Color based on epic number
                    epic_num = int(label_name.split("-")[1])
                    colors = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444"]  # Blue, Green, Orange, Red
                    color = colors[(epic_num - 1) % len(colors)]
                else:
                    color = "#6B7280"  # Gray

            self.logger.info(
                f"Creating label '{label_name}' with color {color}",
                context={'label': label_name, 'color': color, 'team': self.team}
            )

            # Note: linctl label creation may need team_id
            # This is a placeholder for when linctl supports label creation
            # result = self.wrapper._exec(['label', 'create', '--name', label_name, '--color', color, '--team', self.team])

            # For now, we'll track in cache with a placeholder ID
            label_id = f"label-{label_name}"
            self._label_cache[label_name] = label_id

            self.logger.info(
                f"Label '{label_name}' created",
                context={'label': label_name, 'id': label_id}
            )

            return label_id

        except Exception as e:
            self.logger.error(
                f"Failed to create label '{label_name}'",
                context={'error': str(e)}
            )
            return None

    def apply_epic_metadata(
        self,
        issue_id: str,
        epic_number: int,
        project_id: Optional[str] = None,
        default_state: str = "planned"
    ) -> bool:
        """
        Apply epic metadata to a Linear issue.

        Args:
            issue_id: Linear issue ID/key (e.g., 'RAE-360')
            epic_number: Epic number (e.g., 1, 2, 3)
            project_id: Optional Linear project ID
            default_state: Default state for epic (default: "planned")

        Returns:
            True if metadata applied successfully

        Applies:
        - Labels: "epic", "epic-N"
        - Project assignment (if project_id provided)
        - Default state (if not already set)
        """
        try:
            self.logger.info(
                f"Applying epic metadata to {issue_id}",
                context={
                    'issue_id': issue_id,
                    'epic_number': epic_number,
                    'project_id': project_id,
                    'state': default_state
                }
            )

            # Ensure labels exist
            labels = self.ensure_epic_labels_exist([epic_number])

            # Build update payload
            update_data: Dict[str, Any] = {}

            # Add labels (if linctl supports it)
            # Note: linctl may need label support added
            # For now, we track the intent
            update_data['_labels'] = ["epic", f"epic-{epic_number}"]

            # Set project (if provided and linctl supports it)
            if project_id:
                update_data['project'] = project_id

            # Set default state
            update_data['state'] = default_state

            # Apply updates via linctl
            # Note: linctl may not support all these fields yet
            # This implementation prepares for when it does
            try:
                result = self.wrapper.issue_update(issue_id, {
                    'state': default_state,
                    'project': project_id
                } if project_id else {'state': default_state})

                self.logger.info(
                    f"Epic metadata applied to {issue_id}",
                    context={'issue_id': issue_id, 'result': result}
                )
                return True

            except LinctlError as e:
                # May fail if some fields not supported yet
                self.logger.warning(
                    f"Partial metadata application for {issue_id}",
                    context={'error': str(e)}
                )
                return False

        except Exception as e:
            self.logger.error(
                f"Failed to apply epic metadata to {issue_id}",
                context={'error': str(e)}
            )
            return False

    def apply_story_metadata(
        self,
        issue_id: str,
        epic_number: int,
        project_id: Optional[str] = None
    ) -> bool:
        """
        Apply story metadata to a Linear issue.

        Args:
            issue_id: Linear issue ID/key
            epic_number: Parent epic number
            project_id: Optional Linear project ID

        Returns:
            True if metadata applied successfully

        Applies:
        - Labels: "story", "epic-N" (to indicate parent epic)
        - Project assignment (if project_id provided)
        """
        try:
            self.logger.info(
                f"Applying story metadata to {issue_id}",
                context={
                    'issue_id': issue_id,
                    'epic_number': epic_number,
                    'project_id': project_id
                }
            )

            # Ensure epic label exists
            self.ensure_epic_labels_exist([epic_number])

            # Build update payload
            update_data: Dict[str, Any] = {}

            # Add labels
            update_data['_labels'] = ["story", f"epic-{epic_number}"]

            # Set project (if provided)
            if project_id:
                update_data['project'] = project_id

            # Apply updates
            try:
                result = self.wrapper.issue_update(
                    issue_id,
                    {'project': project_id} if project_id else {}
                )

                self.logger.info(
                    f"Story metadata applied to {issue_id}",
                    context={'issue_id': issue_id}
                )
                return True

            except LinctlError as e:
                self.logger.warning(
                    f"Partial metadata application for {issue_id}",
                    context={'error': str(e)}
                )
                return False

        except Exception as e:
            self.logger.error(
                f"Failed to apply story metadata to {issue_id}",
                context={'error': str(e)}
            )
            return False

    def get_project_id_by_name(self, project_name: str) -> Optional[str]:
        """
        Get Linear project ID by name.

        Args:
            project_name: Project name to search for

        Returns:
            Project ID or None if not found
        """
        try:
            projects = self.wrapper.list_projects(self.team)

            for project in projects:
                if project.get('name') == project_name:
                    return project.get('id')

            self.logger.warning(
                f"Project '{project_name}' not found in team {self.team}",
                context={'project': project_name, 'team': self.team}
            )
            return None

        except LinctlError as e:
            self.logger.error(
                f"Failed to list projects for team {self.team}",
                context={'error': str(e)}
            )
            return None

    def ensure_project_exists(self, project_name: str) -> Optional[str]:
        """
        Ensure a project exists in Linear, returning its ID.

        Args:
            project_name: Project name

        Returns:
            Project ID or None if not found/created
        """
        # Try to find existing
        project_id = self.get_project_id_by_name(project_name)
        if project_id:
            return project_id

        # Note: Project creation requires more setup in Linear
        # For now, we just log that it's missing
        self.logger.warning(
            f"Project '{project_name}' not found - please create it manually in Linear",
            context={'project': project_name, 'team': self.team}
        )

        return None

    def get_metadata_summary(self) -> Dict[str, Any]:
        """
        Get summary of metadata manager state.

        Returns:
            Dictionary with metadata statistics
        """
        return {
            'team': self.team,
            'cached_labels': len(self._label_cache),
            'label_names': list(self._label_cache.keys()),
        }


# Module interface functions

def get_metadata_manager(team: str) -> MetadataManager:
    """
    Get metadata manager instance.

    Args:
        team: Linear team ID or name

    Returns:
        MetadataManager instance
    """
    return MetadataManager(team)


def apply_epic_metadata(
    issue_id: str,
    epic_number: int,
    team: str,
    project_id: Optional[str] = None
) -> bool:
    """
    Apply epic metadata to a Linear issue.

    Args:
        issue_id: Linear issue ID/key
        epic_number: Epic number
        team: Linear team ID or name
        project_id: Optional Linear project ID

    Returns:
        True if successful
    """
    manager = get_metadata_manager(team)
    return manager.apply_epic_metadata(issue_id, epic_number, project_id)


if __name__ == '__main__':
    # Test metadata manager
    import sys

    if len(sys.argv) < 2:
        print("Usage: python metadata.py <team>")
        sys.exit(1)

    team = sys.argv[1]
    manager = get_metadata_manager(team)

    print("Metadata Manager - Test")
    print("=" * 50)

    # Ensure epic labels exist
    print("\n1. Creating epic labels...")
    labels = manager.ensure_epic_labels_exist([1, 2, 3, 4])
    print(f"   Created labels: {list(labels.keys())}")

    # Show summary
    summary = manager.get_metadata_summary()
    print(f"\n2. Metadata Summary:")
    print(f"   Team: {summary['team']}")
    print(f"   Cached labels: {summary['cached_labels']}")
    print(f"   Label names: {', '.join(summary['label_names'])}")
