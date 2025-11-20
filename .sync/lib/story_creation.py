#!/usr/bin/env python3
"""
Story creation and formatting for Linear synchronization.

Handles:
- Story discovery from BMAD content
- Content formatting for Linear issue creation
- Story metadata and label assignment
- Hierarchical relationship setup (story -> epic)
"""

import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone

from content_parser import ContentParser, ParserError
from linctl_wrapper import get_wrapper, LinctlError
from logger import get_logger


@dataclass
class StoryContent:
    """Represents discovered BMAD story content."""

    epic_number: int
    story_number: int
    story_key: str  # e.g., "3-2-story-content-generation"
    title: str
    description: str
    acceptance_criteria: List[str]
    technical_notes: str
    tasks: List[str]  # Tasks/subtasks for tracking
    source_file: Path
    status: str  # drafted, ready-for-dev, in-progress, review, done
    metadata: Dict[str, Any]

    def to_linear_description(self) -> str:
        """
        Format story content for Linear issue description.

        Returns:
            Markdown formatted description for Linear
        """
        parts = []

        # Story description/user story
        if self.description:
            parts.append(self.description.strip())

        # Acceptance Criteria as checkboxes
        if self.acceptance_criteria:
            parts.append("\n\n## Acceptance Criteria\n")
            for i, ac in enumerate(self.acceptance_criteria, 1):
                parts.append(f"{i}. {ac}")

        # Technical Notes (collapsible if long)
        if self.technical_notes:
            tech_notes = self.technical_notes.strip()
            if len(tech_notes) > 500:
                # Use details/summary for long technical notes
                parts.append("\n\n<details><summary>Technical Notes</summary>\n")
                parts.append(f"\n{tech_notes}\n")
                parts.append("</details>")
            else:
                parts.append("\n\n## Technical Notes\n")
                parts.append(tech_notes)

        # Tasks/Subtasks overview (for reference)
        if self.tasks:
            parts.append("\n\n## Implementation Tasks\n")
            for task in self.tasks[:5]:  # Show first 5 tasks
                parts.append(f"- {task}")
            if len(self.tasks) > 5:
                parts.append(f"- ... and {len(self.tasks) - 5} more tasks")

        # Traceability footer
        parts.append(f"\n\n---")
        parts.append(f"\n**Story Key:** `{self.story_key}`")
        parts.append(f"\n**Source:** `{self.source_file.name}`")
        parts.append(f"\n**Epic:** {self.epic_number}")

        return "".join(parts)

    def get_story_identifier(self) -> str:
        """
        Get human-readable story identifier.

        Returns:
            Story identifier like "Story 3.2"
        """
        return f"Story {self.epic_number}.{self.story_number}"


class StoryCreationManager:
    """
    Manages story discovery, formatting, and creation in Linear.
    """

    def __init__(self, bmad_root: Path):
        """
        Initialize story creation manager.

        Args:
            bmad_root: Root directory of BMAD project
        """
        self.bmad_root = Path(bmad_root)
        self.docs_bmad = self.bmad_root / 'docs-bmad'
        self.stories_dir = self.docs_bmad / 'stories'
        self.parser = ContentParser()
        self.wrapper = get_wrapper()
        self.logger = get_logger()

    def discover_stories(self, epic_number: Optional[int] = None) -> List[StoryContent]:
        """
        Discover all BMAD stories, optionally filtered by epic.

        Searches for:
        - Individual story files: N-M-story-name.md in stories/
        - Stories from epics.md master file

        Args:
            epic_number: Optional epic number to filter by

        Returns:
            List of discovered StoryContent objects
        """
        stories = []

        # Discover from individual story files
        if self.stories_dir.exists():
            for story_file in self.stories_dir.glob("*.md"):
                # Skip context files and epic files
                if story_file.stem.endswith('.context') or story_file.stem.startswith('epic-'):
                    continue

                # Check if matches story pattern: N-M-name.md
                story_key_match = re.match(r'^(\d+)-(\d+)-', story_file.stem)
                if story_key_match:
                    story_epic = int(story_key_match.group(1))

                    # Filter by epic if specified
                    if epic_number is not None and story_epic != epic_number:
                        continue

                    story = self._parse_story_file(story_file)
                    if story:
                        stories.append(story)

        return sorted(stories, key=lambda s: (s.epic_number, s.story_number))

    def _parse_story_file(self, story_file: Path) -> Optional[StoryContent]:
        """
        Parse individual story file.

        Args:
            story_file: Path to story markdown file

        Returns:
            StoryContent or None if parsing fails
        """
        try:
            # Use existing ContentParser for basic parsing
            parsed_data = self.parser.parse_story_file(story_file)

            # Read full content for additional sections
            content = story_file.read_text(encoding='utf-8')

            # Extract description/user story (between ## Story and ## Acceptance Criteria)
            description = self._extract_section(content, r'## Story', r'## Acceptance Criteria')

            # Extract technical notes
            technical_notes = self._extract_section(content, r'## Dev Notes', r'## (Change Log|Dev Agent Record|File List)')

            # Extract tasks (for tracking, not included in Linear description by default)
            tasks = self._extract_tasks(content)

            # Extract story key from filename
            story_key = story_file.stem

            return StoryContent(
                epic_number=parsed_data['epic_number'],
                story_number=parsed_data['story_number'],
                story_key=story_key,
                title=parsed_data['title'],
                description=description,
                acceptance_criteria=parsed_data['acceptance_criteria'],
                technical_notes=technical_notes,
                tasks=tasks,
                source_file=story_file,
                status=parsed_data.get('status', 'drafted'),
                metadata={}
            )

        except ParserError as e:
            self.logger.error(
                f"Failed to parse story file: {story_file}",
                context={'error': str(e)}
            )
            return None
        except Exception as e:
            self.logger.error(
                f"Unexpected error parsing story file: {story_file}",
                context={'error': str(e), 'type': type(e).__name__}
            )
            return None

    def _extract_section(self, content: str, start_pattern: str, end_pattern: str) -> str:
        """
        Extract content between two markdown sections.

        Args:
            content: Full markdown content
            start_pattern: Regex pattern for section start
            end_pattern: Regex pattern for section end

        Returns:
            Extracted section content (empty string if not found)
        """
        start_match = re.search(start_pattern, content, re.MULTILINE)
        if not start_match:
            return ""

        start_pos = start_match.end()

        # Find next section
        end_match = re.search(end_pattern, content[start_pos:], re.MULTILINE)
        if end_match:
            end_pos = start_pos + end_match.start()
            section = content[start_pos:end_pos].strip()
        else:
            section = content[start_pos:].strip()

        return section

    def _extract_tasks(self, content: str) -> List[str]:
        """
        Extract task list from Tasks/Subtasks section.

        Args:
            content: Full markdown content

        Returns:
            List of task descriptions (without checkboxes)
        """
        tasks = []

        # Find Tasks / Subtasks section
        section_match = re.search(r'## Tasks / Subtasks', content, re.MULTILINE)
        if not section_match:
            return tasks

        start_pos = section_match.end()

        # Find next section
        next_section = re.search(r'^## ', content[start_pos:], re.MULTILINE)
        if next_section:
            end_pos = start_pos + next_section.start()
            section_content = content[start_pos:end_pos]
        else:
            section_content = content[start_pos:]

        # Extract task descriptions (lines with checkboxes)
        for line in section_content.splitlines():
            line = line.strip()
            # Match: - [ ] Task description or ### Task N: Description
            checkbox_match = re.match(r'^-\s*\[[ x]\]\s*(.+)$', line)
            if checkbox_match:
                tasks.append(checkbox_match.group(1).strip())

        return tasks

    def format_story_for_linear(
        self,
        story: StoryContent,
        team: str,
        project_id: Optional[str] = None,
        parent_epic_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Format story content for Linear issue creation.

        Args:
            story: Story content to format
            team: Linear team ID/name
            project_id: Optional Linear project ID
            parent_epic_id: Optional parent epic issue ID (for linking)

        Returns:
            Dictionary suitable for linctl issue_create
        """
        # Format: 📋 STORY: Title (no number - Linear ID shows it)
        title = f"📋 STORY: {story.title}"
        description = story.to_linear_description()

        issue_data = {
            'title': title,
            'team': team,
            'description': description,
        }

        if project_id:
            issue_data['project'] = project_id

        if parent_epic_id:
            issue_data['parent'] = parent_epic_id

        return issue_data

    def create_story_in_linear(
        self,
        story: StoryContent,
        team: str,
        project_id: Optional[str] = None,
        parent_epic_id: Optional[str] = None,
        auto_assign: bool = False,
        apply_labels: bool = True
    ) -> Dict[str, Any]:
        """
        Create story as Linear issue.

        Args:
            story: Story content to create
            team: Linear team ID/name
            project_id: Optional Linear project ID
            parent_epic_id: Optional parent epic issue ID
            auto_assign: Whether to auto-assign to current user
            apply_labels: Whether to apply story labels

        Returns:
            Created issue details with Linear UUID and issue key

        Raises:
            LinctlError: If creation fails
        """
        issue_data = self.format_story_for_linear(story, team, project_id, parent_epic_id)

        try:
            self.logger.info(
                f"Creating story {story.story_key} in Linear",
                context={'title': issue_data['title'], 'team': team}
            )

            result = self.wrapper.issue_create(issue_data)

            # Extract Linear UUID and issue key
            linear_uuid = result.get('id', result.get('uuid', ''))
            issue_key = result.get('key', result.get('identifier', ''))

            # Set default state based on story status
            state_mapping = {
                'drafted': 'backlog',
                'ready-for-dev': 'todo',
                'in-progress': 'in progress',
                'review': 'in review',
                'done': 'done'
            }
            default_state = state_mapping.get(story.status, 'backlog')

            try:
                self.wrapper.issue_update(issue_key, {'state': default_state})
            except Exception:
                # State update may fail - that's okay
                pass

            self.logger.info(
                f"Story {story.story_key} created successfully",
                context={
                    'issue_key': issue_key,
                    'linear_uuid': linear_uuid,
                    'story_identifier': story.get_story_identifier()
                }
            )

            return {
                'success': True,
                'story_key': story.story_key,
                'story_identifier': story.get_story_identifier(),
                'linear_uuid': linear_uuid,
                'issue_key': issue_key,
                'issue_data': issue_data,
                'result': result
            }

        except LinctlError as e:
            self.logger.error(
                f"Failed to create story {story.story_key}",
                context={'error': str(e), 'title': story.title}
            )
            raise

    def get_story_creation_preview(
        self,
        story: StoryContent,
        team: str
    ) -> Dict[str, Any]:
        """
        Generate preview of what will be created for a story.

        Args:
            story: Story to preview
            team: Linear team ID/name

        Returns:
            Preview data including formatted content
        """
        issue_data = self.format_story_for_linear(story, team)

        return {
            'story_key': story.story_key,
            'story_identifier': story.get_story_identifier(),
            'title': issue_data['title'],
            'description_preview': issue_data['description'][:300] + '...' if len(issue_data['description']) > 300 else issue_data['description'],
            'acceptance_criteria_count': len(story.acceptance_criteria),
            'task_count': len(story.tasks),
            'status': story.status,
            'source_file': str(story.source_file),
            'full_issue_data': issue_data
        }


# Module interface functions

def discover_all_stories(
    bmad_root: Path,
    epic_number: Optional[int] = None
) -> List[StoryContent]:
    """
    Discover all BMAD stories.

    Args:
        bmad_root: Root directory of BMAD project
        epic_number: Optional epic number to filter by

    Returns:
        List of discovered stories
    """
    manager = StoryCreationManager(bmad_root)
    return manager.discover_stories(epic_number)


def create_story(
    story: StoryContent,
    team: str,
    project_id: Optional[str] = None,
    parent_epic_id: Optional[str] = None,
    bmad_root: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Create story in Linear.

    Args:
        story: Story content to create
        team: Linear team ID/name
        project_id: Optional Linear project ID
        parent_epic_id: Optional parent epic issue ID
        bmad_root: Optional BMAD root (default: current directory)

    Returns:
        Created issue details
    """
    if bmad_root is None:
        bmad_root = Path.cwd()

    manager = StoryCreationManager(bmad_root)
    return manager.create_story_in_linear(story, team, project_id, parent_epic_id)


def preview_story_creation(
    story: StoryContent,
    team: str,
    bmad_root: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Preview what will be created for a story.

    Args:
        story: Story to preview
        team: Linear team ID/name
        bmad_root: Optional BMAD root

    Returns:
        Preview data
    """
    if bmad_root is None:
        bmad_root = Path.cwd()

    manager = StoryCreationManager(bmad_root)
    return manager.get_story_creation_preview(story, team)
