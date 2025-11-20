#!/usr/bin/env python3
"""
Epic creation and formatting for Linear synchronization.

Handles:
- Epic discovery from BMAD content
- Content formatting for Linear issue creation
- Epic metadata and label assignment
- Hierarchical relationship setup
"""

import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone

from content_scanner import ContentScanner
from content_parser import ContentParser
from epic_numbering import get_numbering_system, EpicNumberRange
from linctl_wrapper import get_wrapper, LinctlError
from logger import get_logger


@dataclass
class EpicContent:
    """Represents discovered BMAD epic content."""

    epic_number: int
    title: str
    description: str
    stories: List[str]  # Story keys
    source_file: Path
    metadata: Dict[str, Any]

    def to_linear_description(self) -> str:
        """
        Format epic content for Linear issue description.

        Returns:
            Markdown formatted description for Linear
        """
        parts = [self.description.strip()]

        if self.stories:
            parts.append("\n\n## Stories")
            for story_key in self.stories:
                parts.append(f"- {story_key}")

        if self.metadata.get('goals'):
            parts.append("\n\n## Goals")
            for goal in self.metadata['goals']:
                parts.append(f"- {goal}")

        # Add source reference
        parts.append(f"\n\n---\n*Source: {self.source_file.name}*")

        return "\n".join(parts)


class EpicCreationManager:
    """
    Manages epic discovery, formatting, and creation in Linear.
    """

    def __init__(self, bmad_root: Path):
        """
        Initialize epic creation manager.

        Args:
            bmad_root: Root directory of BMAD project
        """
        self.bmad_root = Path(bmad_root)
        self.docs_bmad = self.bmad_root / 'docs-bmad'
        self.scanner = ContentScanner(self.bmad_root)
        self.parser = ContentParser()
        self.numbering = get_numbering_system()
        self.wrapper = get_wrapper()
        self.logger = get_logger()

    def discover_epics(self) -> List[EpicContent]:
        """
        Discover all BMAD epics.

        Searches for:
        - epics.md with "## Epic N: Title" sections
        - epic-N-context.md individual files
        - epic-N.md individual files

        Returns:
            List of discovered EpicContent objects
        """
        epics = []

        # Check epics.md master file
        epics_file = self.docs_bmad / 'epics.md'
        if epics_file.exists():
            epics.extend(self._parse_epics_file(epics_file))

        # Check individual epic files
        for pattern in ['epic-*-context.md', 'epic-*.md']:
            for epic_file in self.docs_bmad.glob(pattern):
                # Skip if epic number already discovered from epics.md
                epic_num = self._extract_epic_number(epic_file.stem)
                if epic_num and not any(e.epic_number == epic_num for e in epics):
                    epic = self._parse_epic_file(epic_file)
                    if epic:
                        epics.append(epic)

        return sorted(epics, key=lambda e: e.epic_number)

    def _extract_epic_number(self, text: str) -> Optional[int]:
        """
        Extract epic number from text.

        Args:
            text: Text to search (filename, heading)

        Returns:
            Epic number or None
        """
        # Try patterns: "epic-3", "Epic 3", "epic 3:"
        patterns = [
            r'epic[-\s](\d+)',
            r'Epic\s+(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None

    def _parse_epics_file(self, epics_file: Path) -> List[EpicContent]:
        """
        Parse epics.md master file.

        Args:
            epics_file: Path to epics.md

        Returns:
            List of discovered epics
        """
        epics = []

        try:
            content = epics_file.read_text(encoding='utf-8')
            lines = content.splitlines()

            current_epic = None
            current_description = []

            for line in lines:
                # Check for epic heading: ## Epic N: Title
                if line.startswith('## Epic '):
                    # Save previous epic
                    if current_epic:
                        current_epic['description'] = '\n'.join(current_description).strip()
                        epics.append(self._create_epic_content(current_epic, epics_file))

                    # Parse new epic
                    match = re.match(r'##\s+Epic\s+(\d+):\s*(.+)', line)
                    if match:
                        current_epic = {
                            'number': int(match.group(1)),
                            'title': match.group(2).strip(),
                            'stories': []
                        }
                        current_description = []

                elif current_epic:
                    # Collect description and story references
                    if line.startswith('### Story '):
                        # Story heading: ### Story 1.1: Title (RAE-363)
                        match = re.match(r'###\s+Story\s+([\d\-\.]+):', line)
                        if match:
                            story_key = match.group(1).replace('.', '-')
                            current_epic['stories'].append(story_key)
                    else:
                        # Description content
                        current_description.append(line)

            # Save last epic
            if current_epic:
                current_epic['description'] = '\n'.join(current_description).strip()
                epics.append(self._create_epic_content(current_epic, epics_file))

        except Exception as e:
            self.logger.error(
                f"Failed to parse epics file: {epics_file}",
                context={'error': str(e)}
            )

        return epics

    def _parse_epic_file(self, epic_file: Path) -> Optional[EpicContent]:
        """
        Parse individual epic file (epic-N-context.md or epic-N.md).

        Args:
            epic_file: Path to epic file

        Returns:
            EpicContent or None if parsing fails
        """
        try:
            epic_num = self._extract_epic_number(epic_file.stem)
            if not epic_num:
                return None

            content = epic_file.read_text(encoding='utf-8')
            lines = content.splitlines()

            # Extract title (first heading)
            title = None
            for line in lines:
                if line.startswith('# '):
                    title = line[2:].strip()
                    # Remove "Epic N:" prefix if present
                    title = re.sub(r'^Epic\s+\d+\s*:?\s*', '', title, flags=re.IGNORECASE)
                    break

            if not title:
                title = f"Epic {epic_num}"

            # Extract description (content up to first ## heading)
            description_lines = []
            in_description = False

            for line in lines:
                if line.startswith('# '):
                    in_description = True
                    continue
                if line.startswith('## '):
                    break
                if in_description:
                    description_lines.append(line)

            description = '\n'.join(description_lines).strip()

            # Extract stories referenced in content
            stories = []
            story_pattern = r'Story\s+([\d\-\.]+)'
            for match in re.finditer(story_pattern, content):
                story_key = match.group(1).replace('.', '-')
                if story_key not in stories:
                    stories.append(story_key)

            # Extract goals if present
            goals = []
            if '## Epic Goals' in content or '## Goals' in content:
                in_goals = False
                for line in lines:
                    if '## Epic Goals' in line or '## Goals' in line:
                        in_goals = True
                        continue
                    if in_goals:
                        if line.startswith('## '):
                            break
                        if line.strip().startswith(('- ', '* ', '1. ')):
                            goal = re.sub(r'^[\-\*\d\.]\s+', '', line.strip())
                            goals.append(goal)

            return EpicContent(
                epic_number=epic_num,
                title=title,
                description=description,
                stories=stories,
                source_file=epic_file,
                metadata={'goals': goals}
            )

        except Exception as e:
            self.logger.error(
                f"Failed to parse epic file: {epic_file}",
                context={'error': str(e)}
            )
            return None

    def _create_epic_content(self, epic_data: Dict[str, Any], source_file: Path) -> EpicContent:
        """
        Create EpicContent from parsed data.

        Args:
            epic_data: Parsed epic data
            source_file: Source file path

        Returns:
            EpicContent object
        """
        return EpicContent(
            epic_number=epic_data['number'],
            title=epic_data['title'],
            description=epic_data.get('description', ''),
            stories=epic_data.get('stories', []),
            source_file=source_file,
            metadata=epic_data.get('metadata', {})
        )

    def format_epic_for_linear(
        self,
        epic: EpicContent,
        team: str,
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Format epic content for Linear issue creation.

        Args:
            epic: Epic content to format
            team: Linear team ID/name
            project_id: Optional Linear project ID

        Returns:
            Dictionary suitable for linctl issue_create
        """
        # Reserve epic number range
        epic_range = self.numbering.reserve_epic_range(epic.epic_number)

        # Format: 📦 EPIC: Title (no number - Linear ID shows it)
        title = f"📦 EPIC: {epic.title}"
        description = epic.to_linear_description()

        issue_data = {
            'title': title,
            'team': team,
            'description': description,
            # Note: State must be set after creation via update
        }

        if project_id:
            issue_data['project'] = project_id

        return issue_data

    def create_epic_in_linear(
        self,
        epic: EpicContent,
        team: str,
        project_id: Optional[str] = None,
        apply_labels: bool = True
    ) -> Dict[str, Any]:
        """
        Create epic as Linear issue.

        Args:
            epic: Epic content to create
            team: Linear team ID/name
            project_id: Optional Linear project ID
            apply_labels: Whether to apply epic labels

        Returns:
            Created issue details with Linear UUID and issue key

        Raises:
            LinctlError: If creation fails
        """
        issue_data = self.format_epic_for_linear(epic, team, project_id)

        try:
            self.logger.info(
                f"Creating epic {epic.epic_number} in Linear",
                context={'title': issue_data['title'], 'team': team}
            )

            result = self.wrapper.issue_create(issue_data)

            # Extract Linear UUID and issue key
            linear_uuid = result.get('id', result.get('uuid', ''))
            issue_key = result.get('key', result.get('identifier', ''))

            # Set default state to 'planned' via update (linctl create doesn't support --state yet)
            try:
                self.wrapper.issue_update(issue_key, {'state': 'planned'})
            except Exception:
                # State update may fail if not supported yet - that's okay
                pass

            self.logger.info(
                f"Epic {epic.epic_number} created successfully",
                context={
                    'issue_key': issue_key,
                    'linear_uuid': linear_uuid,
                    'epic_number': epic.epic_number
                }
            )

            return {
                'success': True,
                'epic_number': epic.epic_number,
                'linear_uuid': linear_uuid,
                'issue_key': issue_key,
                'issue_data': issue_data,
                'result': result
            }

        except LinctlError as e:
            self.logger.error(
                f"Failed to create epic {epic.epic_number}",
                context={'error': str(e), 'epic': epic.title}
            )
            raise

    def get_epic_creation_preview(self, epic: EpicContent, team: str) -> Dict[str, Any]:
        """
        Generate preview of what will be created for an epic.

        Args:
            epic: Epic to preview
            team: Linear team ID/name

        Returns:
            Preview data including estimated issue number and formatted content
        """
        epic_range = self.numbering.calculate_epic_range(epic.epic_number)
        issue_data = self.format_epic_for_linear(epic, team, project_id=None)

        return {
            'epic_number': epic.epic_number,
            'title': issue_data['title'],
            'estimated_issue_range': f"RAE-{epic_range.range_start} to RAE-{epic_range.range_end}",
            'description_preview': issue_data['description'][:200] + '...' if len(issue_data['description']) > 200 else issue_data['description'],
            'story_count': len(epic.stories),
            'stories': epic.stories,
            'source_file': str(epic.source_file),
            'full_issue_data': issue_data
        }


# Module interface functions

def discover_all_epics(bmad_root: Path) -> List[EpicContent]:
    """
    Discover all BMAD epics.

    Args:
        bmad_root: Root directory of BMAD project

    Returns:
        List of discovered epics
    """
    manager = EpicCreationManager(bmad_root)
    return manager.discover_epics()


def create_epic(
    epic: EpicContent,
    team: str,
    project_id: Optional[str] = None,
    bmad_root: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Create epic in Linear.

    Args:
        epic: Epic content to create
        team: Linear team ID/name
        project_id: Optional Linear project ID
        bmad_root: Optional BMAD root (default: current directory)

    Returns:
        Created issue details
    """
    if bmad_root is None:
        bmad_root = Path.cwd()

    manager = EpicCreationManager(bmad_root)
    return manager.create_epic_in_linear(epic, team, project_id)


def preview_epic_creation(
    epic: EpicContent,
    team: str,
    bmad_root: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Preview what will be created for an epic.

    Args:
        epic: Epic to preview
        team: Linear team ID/name
        bmad_root: Optional BMAD root

    Returns:
        Preview data
    """
    if bmad_root is None:
        bmad_root = Path.cwd()

    manager = EpicCreationManager(bmad_root)
    return manager.get_epic_creation_preview(epic, team)
