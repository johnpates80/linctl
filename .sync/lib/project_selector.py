#!/usr/bin/env python3
"""
Interactive project selector with fuzzy search for Linear projects.

Handles missing project configuration by allowing users to search
and select from available Linear projects.
"""

import os
import sys
from typing import Optional, List, Dict, Any
from pathlib import Path

from linctl_wrapper import get_wrapper, LinctlError
from logger import get_logger


class ProjectSelector:
    """
    Interactive project selection and environment persistence.
    """

    def __init__(self, team: str):
        """
        Initialize project selector.

        Args:
            team: Linear team ID or name
        """
        self.team = team
        self.wrapper = get_wrapper()
        self.logger = get_logger()

    def get_all_projects(self) -> List[Dict[str, Any]]:
        """
        Get all projects from Linear for the team.

        Returns:
            List of project dictionaries with id, name, state
        """
        try:
            result = self.wrapper.run_command([
                'project', 'list',
                '--team', self.team,
                '--json'
            ])

            if result and isinstance(result, dict) and 'projects' in result:
                return result['projects']
            return []

        except LinctlError as e:
            self.logger.error(f"Failed to list projects: {e}")
            return []

    def fuzzy_search(self, query: str, projects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Fuzzy search projects by name.

        Args:
            query: Search query (partial name)
            projects: List of all projects

        Returns:
            Filtered list of matching projects
        """
        query_lower = query.lower()
        matches = []

        for project in projects:
            name = project.get('name', '').lower()

            # Exact match
            if query_lower == name:
                matches.insert(0, project)  # Priority
            # Starts with query
            elif name.startswith(query_lower):
                matches.append(project)
            # Contains query
            elif query_lower in name:
                matches.append(project)

        return matches

    def prompt_for_project(self) -> Optional[str]:
        """
        Interactively prompt user for project selection.

        Returns:
            Selected project ID or None if cancelled
        """
        print("\n🔍 Project ID not found. Let's find your Linear project.\n")

        # Get all projects
        projects = self.get_all_projects()

        if not projects:
            print("❌ No projects found in Linear.")
            print(f"   Team: {self.team}")
            print("\nPlease:")
            print("  1. Create a project in Linear first")
            print("  2. Or check your LINEAR_TEAM setting")
            return None

        # Show available projects
        print(f"Found {len(projects)} project(s) in team '{self.team}':\n")

        for i, proj in enumerate(projects[:10], 1):
            state = proj.get('state', 'unknown')
            print(f"  {i}. {proj['name']} ({state})")

        if len(projects) > 10:
            print(f"  ... and {len(projects) - 10} more")

        print()

        # Get user input
        while True:
            search_query = input("Enter project name (or part of it): ").strip()

            if not search_query:
                print("❌ Cancelled.")
                return None

            # Search
            matches = self.fuzzy_search(search_query, projects)

            if not matches:
                print(f"❌ No matches for '{search_query}'. Try again.\n")
                continue

            # Show matches
            print(f"\n✅ Found {len(matches)} match(es):\n")
            for i, proj in enumerate(matches[:5], 1):
                state = proj.get('state', 'unknown')
                print(f"  {i}. {proj['name']} ({state})")

            if len(matches) > 5:
                print(f"  ... and {len(matches) - 5} more")

            print("\n  0. Search again")
            print()

            # Get selection
            try:
                choice = input("Select project number (or 0 to search again): ").strip()

                if choice == '0':
                    print()
                    continue

                idx = int(choice) - 1

                if 0 <= idx < len(matches):
                    selected = matches[idx]
                    print(f"\n✅ Selected: {selected['name']}")
                    return selected['id']
                else:
                    print("❌ Invalid selection. Try again.\n")

            except ValueError:
                print("❌ Invalid input. Enter a number.\n")
            except KeyboardInterrupt:
                print("\n❌ Cancelled.")
                return None

    def save_to_config(self, project_id: str, project_name: str) -> None:
        """
        Save project ID to .sync/config/sync_config.yaml.

        Args:
            project_id: Linear project ID (UUID)
            project_name: Project name for reference
        """
        try:
            import yaml
        except ImportError:
            print("⚠️  PyYAML not available, saving to environment only")
            os.environ['LINEAR_PROJECT'] = project_id
            return

        config_path = Path('.sync/config/sync_config.yaml')

        if not config_path.exists():
            print(f"⚠️  Config file not found: {config_path}")
            print("   Saving to environment variable instead")
            os.environ['LINEAR_PROJECT'] = project_id
            return

        try:
            # Load existing config
            config = yaml.safe_load(config_path.read_text(encoding='utf-8'))

            # Update linear section
            if 'linear' not in config:
                config['linear'] = {}

            config['linear']['project_id'] = project_id
            config['linear']['project_name'] = project_name

            # Save back
            config_path.write_text(yaml.dump(config, default_flow_style=False), encoding='utf-8')

            print(f"\n💾 Saved to {config_path}")
            print(f"   Project: {project_name}")
            print(f"   ID: {project_id}")
            print("\n✅ Configuration saved (version controlled)")

            # Also set for current session
            os.environ['LINEAR_PROJECT'] = project_id

        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")
            print(f"⚠️  Failed to save to config: {e}")
            print("   Saving to environment variable instead")
            os.environ['LINEAR_PROJECT'] = project_id

    def ensure_project_id(self, current_project_id: Optional[str] = None) -> Optional[str]:
        """
        Ensure project ID is available, prompting user if needed.

        Args:
            current_project_id: Current project ID from config/env

        Returns:
            Project ID or None if not available/cancelled
        """
        if current_project_id:
            # Validate it exists
            projects = self.get_all_projects()
            if any(p['id'] == current_project_id for p in projects):
                return current_project_id

            print(f"⚠️  Configured project ID not found: {current_project_id}")

        # Prompt for selection
        project_id = self.prompt_for_project()

        if project_id:
            # Get project name
            projects = self.get_all_projects()
            project = next((p for p in projects if p['id'] == project_id), None)

            if project:
                self.save_to_config(project_id, project['name'])

        return project_id


def get_project_selector(team: str) -> ProjectSelector:
    """
    Get ProjectSelector instance.

    Args:
        team: Linear team ID or name

    Returns:
        ProjectSelector instance
    """
    return ProjectSelector(team)


# Example usage
if __name__ == '__main__':
    import sys

    team = sys.argv[1] if len(sys.argv) > 1 else 'RAE'

    selector = ProjectSelector(team)
    project_id = selector.ensure_project_id()

    if project_id:
        print(f"\n✅ Project ID: {project_id}")
        sys.exit(0)
    else:
        print("\n❌ No project selected")
        sys.exit(1)
