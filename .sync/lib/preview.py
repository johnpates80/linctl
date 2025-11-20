#!/usr/bin/env python3
"""
Preview module for BMAD sync operations.

Provides preview and dry-run capabilities before sync execution.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum

from sync_engine import SyncOperation
from content_updater import ContentUpdate, FieldChange
from renumber_engine import RenumberMapping


class ChangeType(Enum):
    """Types of changes that can occur."""
    ADDITION = "addition"
    MODIFICATION = "modification"
    DELETION = "deletion"


class Color:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    DIM = '\033[2m'


@dataclass
class PreviewItem:
    """Represents a single change to be previewed."""
    change_type: ChangeType
    content_key: str
    content_type: str
    title: Optional[str] = None
    action: Optional[str] = None  # 'create' | 'update'
    previous_content: Optional[str] = None
    current_content: Optional[str] = None
    previous_hash: Optional[str] = None
    current_hash: Optional[str] = None
    state_change: Optional[Tuple[str, str]] = None  # (from_state, to_state)
    issue_id: Optional[str] = None
    dependencies: List[str] = None  # List of dependent content keys
    risk_level: str = "low"  # 'low', 'medium', 'high'
    planned_state: Optional[str] = None  # target state to apply
    planned_labels: Optional[List[str]] = None  # labels to apply


@dataclass
class ImpactAnalysis:
    """Impact analysis for sync operations."""
    total_changes: int
    affected_issues: int
    state_transitions: List[Tuple[str, str, str]]  # (content_key, from_state, to_state)
    dependencies: Dict[str, List[str]]  # content_key -> list of dependent keys
    risk_summary: Dict[str, int]  # risk_level -> count
    estimated_api_calls: int


class PreviewGenerator:
    """Generates preview information for sync operations."""

    def __init__(self, colored: bool = True):
        """
        Initialize preview generator.

        Args:
            colored: Whether to use ANSI color codes in output
        """
        self.colored = colored

    def generate_preview(self, operations: List[SyncOperation],
                        previous_index: Optional[Dict[str, Any]] = None,
                        current_index: Optional[Dict[str, Any]] = None) -> List[PreviewItem]:
        """
        Generate preview items from sync operations.

        Args:
            operations: List of sync operations to preview
            previous_index: Previous content index (optional, for detailed diffs)
            current_index: Current content index (optional, for detailed diffs)

        Returns:
            List of PreviewItem objects
        """
        items = []

        for op in operations:
            # Determine change type
            change_type = self._determine_change_type(op)

            # Extract state change if available
            state_change = None
            if previous_index and current_index:
                state_change = self._extract_state_change(
                    op.content_key,
                    previous_index,
                    current_index
                )

            # Extract content for diff if available
            prev_content, curr_content = self._extract_content_for_diff(
                op.content_key,
                previous_index,
                current_index
            )

            item = PreviewItem(
                change_type=change_type,
                content_key=op.content_key,
                content_type=op.content_type,
                title=op.title,
                action=op.action,
                previous_content=prev_content,
                current_content=curr_content,
                previous_hash=op.previous_hash,
                current_hash=op.current_hash,
                state_change=state_change,
                issue_id=op.issue_id,
                planned_state=getattr(op, 'state', None),
                planned_labels=getattr(op, 'labels', None)
            )
            items.append(item)

        return items

    def render_preview(self, items: List[PreviewItem], detailed: bool = False,
                      show_impact: bool = True,
                      previous_index: Optional[Dict[str, Any]] = None,
                      current_index: Optional[Dict[str, Any]] = None) -> str:
        """
        Render preview items as formatted text.

        Args:
            items: List of preview items
            detailed: Include detailed diffs
            show_impact: Include impact analysis
            previous_index: Previous content index (for impact analysis)
            current_index: Current content index (for impact analysis)

        Returns:
            Formatted preview text
        """
        lines = []

        # Header
        lines.append(self._format_header("BMAD SYNC PREVIEW"))
        lines.append("")

        # Summary
        summary = self._generate_summary(items)
        lines.append(self._format_section("SUMMARY"))
        lines.append(summary)
        lines.append("")

        # Impact Analysis (if enabled)
        if show_impact and (previous_index or current_index):
            analysis = self.analyze_impact(items, previous_index, current_index)
            impact_text = self.render_impact_analysis(analysis)
            lines.append(impact_text)

        # Changes by type
        additions = [i for i in items if i.change_type == ChangeType.ADDITION]
        modifications = [i for i in items if i.change_type == ChangeType.MODIFICATION]
        deletions = [i for i in items if i.change_type == ChangeType.DELETION]

        if additions:
            lines.append(self._format_section("ADDITIONS", Color.GREEN))
            for item in additions:
                lines.append(self._format_change_item(item, detailed))
            lines.append("")

        if modifications:
            lines.append(self._format_section("MODIFICATIONS", Color.YELLOW))
            for item in modifications:
                lines.append(self._format_change_item(item, detailed))
            lines.append("")

        if deletions:
            lines.append(self._format_section("DELETIONS", Color.RED))
            for item in deletions:
                lines.append(self._format_change_item(item, detailed))
            lines.append("")

        # Footer
        lines.append(self._format_separator())

        return "\n".join(lines)

    def _determine_change_type(self, op: SyncOperation) -> ChangeType:
        """Determine the type of change from operation."""
        if op.action == "create" or op.reason == "added":
            return ChangeType.ADDITION
        elif op.reason == "deleted" or op.reason == "removed":
            return ChangeType.DELETION
        else:
            return ChangeType.MODIFICATION

    def _extract_state_change(self, content_key: str,
                              previous_index: Dict[str, Any],
                              current_index: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """Extract state change for content."""
        # Check in stories
        prev_story = previous_index.get('stories', {}).get(content_key)
        curr_story = current_index.get('stories', {}).get(content_key)

        if prev_story and curr_story:
            prev_state = prev_story.get('bmad_status')
            curr_state = curr_story.get('bmad_status')
            if prev_state != curr_state:
                return (prev_state, curr_state)

        # Check in epics
        prev_epic = previous_index.get('epics', {}).get(content_key)
        curr_epic = current_index.get('epics', {}).get(content_key)

        if prev_epic and curr_epic:
            prev_state = prev_epic.get('bmad_status')
            curr_state = curr_epic.get('bmad_status')
            if prev_state != curr_state:
                return (prev_state, curr_state)

        return None

    def _extract_content_for_diff(self, content_key: str,
                                  previous_index: Optional[Dict[str, Any]],
                                  current_index: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
        """Extract content strings for diff generation."""
        if not (previous_index and current_index):
            return None, None

        # For stories
        prev_story = previous_index.get('stories', {}).get(content_key)
        curr_story = current_index.get('stories', {}).get(content_key)

        if prev_story and curr_story:
            prev_content = prev_story.get('description', '')
            curr_content = curr_story.get('description', '')
            return prev_content, curr_content

        # For epics
        prev_epic = previous_index.get('epics', {}).get(content_key)
        curr_epic = current_index.get('epics', {}).get(content_key)

        if prev_epic and curr_epic:
            prev_content = prev_epic.get('description', '')
            curr_content = curr_epic.get('description', '')
            return prev_content, curr_content

        return None, None

    def _generate_summary(self, items: List[PreviewItem]) -> str:
        """Generate summary statistics."""
        additions = sum(1 for i in items if i.change_type == ChangeType.ADDITION)
        modifications = sum(1 for i in items if i.change_type == ChangeType.MODIFICATION)
        deletions = sum(1 for i in items if i.change_type == ChangeType.DELETION)
        total = len(items)

        lines = []
        lines.append(f"  Total Changes: {self._colorize(str(total), Color.BOLD)}")
        lines.append(f"  {self._colorize('✓', Color.GREEN)} Additions: {additions}")
        lines.append(f"  {self._colorize('~', Color.YELLOW)} Modifications: {modifications}")
        lines.append(f"  {self._colorize('✗', Color.RED)} Deletions: {deletions}")

        return "\n".join(lines)

    def _format_change_item(self, item: PreviewItem, detailed: bool = False) -> str:
        """Format a single change item."""
        lines = []

        # Icon based on change type
        if item.change_type == ChangeType.ADDITION:
            icon = self._colorize("+ ", Color.GREEN)
        elif item.change_type == ChangeType.MODIFICATION:
            icon = self._colorize("~ ", Color.YELLOW)
        else:
            icon = self._colorize("- ", Color.RED)

        # Main line
        content_type_str = self._colorize(f"[{item.content_type}]", Color.CYAN)
        title_str = item.title or "(no title)"
        lines.append(f"  {icon}{content_type_str} {item.content_key}")
        lines.append(f"    {self._colorize('Title:', Color.DIM)} {title_str}")

        # Action
        if item.action:
            action_str = self._colorize(item.action.upper(), Color.BOLD)
            lines.append(f"    {self._colorize('Action:', Color.DIM)} {action_str}")

        # State change
        if item.state_change:
            from_state, to_state = item.state_change
            state_str = f"{from_state} → {to_state}"
            lines.append(f"    {self._colorize('State:', Color.DIM)} {state_str}")

        # Planned state for additions or when no previous state captured
        if (not item.state_change) and item.planned_state:
            lines.append(f"    {self._colorize('Planned State:', Color.DIM)} {item.planned_state}")

        # Planned labels (if present)
        if item.planned_labels:
            labels_str = ", ".join(item.planned_labels)
            lines.append(f"    {self._colorize('Labels:', Color.DIM)} {labels_str}")

        # Issue ID
        if item.issue_id:
            lines.append(f"    {self._colorize('Issue:', Color.DIM)} {item.issue_id}")

        # Hashes (abbreviated)
        if item.previous_hash and item.current_hash:
            prev_short = item.previous_hash[:8]
            curr_short = item.current_hash[:8]
            lines.append(f"    {self._colorize('Hash:', Color.DIM)} {prev_short} → {curr_short}")

        # Detailed diff
        if detailed and item.previous_content and item.current_content:
            diff_lines = self._generate_diff(item.previous_content, item.current_content)
            if diff_lines:
                lines.append(f"    {self._colorize('Diff:', Color.DIM)}")
                for diff_line in diff_lines[:10]:  # Limit to 10 lines
                    lines.append(f"      {diff_line}")
                if len(diff_lines) > 10:
                    lines.append(f"      {self._colorize('... (truncated)', Color.DIM)}")

        lines.append("")  # Blank line between items
        return "\n".join(lines)

    def _generate_diff(self, old_content: str, new_content: str) -> List[str]:
        """Generate unified diff between two content strings."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm='',
            n=2  # Context lines
        )

        colored_lines = []
        for line in diff:
            if line.startswith('+++') or line.startswith('---'):
                continue  # Skip file headers
            elif line.startswith('+'):
                colored_lines.append(self._colorize(line.rstrip(), Color.GREEN))
            elif line.startswith('-'):
                colored_lines.append(self._colorize(line.rstrip(), Color.RED))
            elif line.startswith('@@'):
                colored_lines.append(self._colorize(line.rstrip(), Color.CYAN))
            else:
                colored_lines.append(line.rstrip())

        return colored_lines

    def _format_header(self, text: str) -> str:
        """Format header with separators."""
        sep = "=" * 60
        return f"{sep}\n{self._colorize(text, Color.BOLD)}\n{sep}"

    def _format_section(self, text: str, color: str = Color.BOLD) -> str:
        """Format section header."""
        return self._colorize(f"━━━ {text} ━━━", color)

    def _format_separator(self) -> str:
        """Format separator line."""
        return "━" * 60

    def _colorize(self, text: str, color: str) -> str:
        """Apply color to text if coloring is enabled."""
        if not self.colored:
            return text
        return f"{color}{text}{Color.RESET}"

    def analyze_impact(self, items: List[PreviewItem],
                      previous_index: Optional[Dict[str, Any]] = None,
                      current_index: Optional[Dict[str, Any]] = None) -> ImpactAnalysis:
        """
        Analyze the impact of sync operations.

        Args:
            items: List of preview items
            previous_index: Previous content index (optional)
            current_index: Current content index (optional)

        Returns:
            ImpactAnalysis object with impact information
        """
        # Count affected Linear issues (those with issue_id)
        affected_issues = sum(1 for i in items if i.issue_id is not None)

        # Collect state transitions
        state_transitions = []
        for item in items:
            if item.state_change:
                from_state, to_state = item.state_change
                state_transitions.append((item.content_key, from_state, to_state))

        # Analyze dependencies
        dependencies = {}
        if current_index:
            dependencies = self._analyze_dependencies(items, current_index)

        # Calculate risk levels and summary
        risk_summary = {"low": 0, "medium": 0, "high": 0}
        for item in items:
            risk = self._assess_risk(item, dependencies.get(item.content_key, []))
            item.risk_level = risk
            risk_summary[risk] += 1

        # Estimate API calls (create = 1, update = 1 per operation)
        estimated_api_calls = len([i for i in items if i.action in ('create', 'update')])

        return ImpactAnalysis(
            total_changes=len(items),
            affected_issues=affected_issues,
            state_transitions=state_transitions,
            dependencies=dependencies,
            risk_summary=risk_summary,
            estimated_api_calls=estimated_api_calls
        )

    def _analyze_dependencies(self, items: List[PreviewItem],
                             current_index: Dict[str, Any]) -> Dict[str, List[str]]:
        """Analyze dependencies between content items."""
        dependencies = {}

        # Extract epic-story relationships
        stories = current_index.get('stories', {})
        for item in items:
            deps = []

            # If this is a story, find its epic
            if item.content_type == 'story' and item.content_key in stories:
                story_data = stories[item.content_key]
                # Extract epic number from story key (e.g., "1-2-auth" -> epic-1)
                if '-' in item.content_key:
                    epic_num = item.content_key.split('-')[0]
                    epic_key = f"epic-{epic_num}"
                    deps.append(epic_key)

            # If this is an epic, find its stories
            if item.content_type == 'epic':
                epic_num = item.content_key.replace('epic-', '')
                for story_key in stories.keys():
                    if story_key.startswith(f"{epic_num}-"):
                        deps.append(story_key)

            if deps:
                dependencies[item.content_key] = deps

        return dependencies

    def _assess_risk(self, item: PreviewItem, dependencies: List[str]) -> str:
        """Assess risk level for a change."""
        risk_score = 0

        # Deletions are risky
        if item.change_type == ChangeType.DELETION:
            risk_score += 3

        # State changes that close/complete things are risky
        if item.state_change:
            from_state, to_state = item.state_change
            if to_state in ('done', 'completed', 'closed'):
                risk_score += 2
            elif to_state in ('review', 'blocked'):
                risk_score += 1

        # Many dependencies increase risk
        if len(dependencies) > 5:
            risk_score += 2
        elif len(dependencies) > 2:
            risk_score += 1

        # Epic changes are more impactful
        if item.content_type == 'epic':
            risk_score += 1

        # Determine level
        if risk_score >= 4:
            return "high"
        elif risk_score >= 2:
            return "medium"
        else:
            return "low"

    def render_impact_analysis(self, analysis: ImpactAnalysis) -> str:
        """
        Render impact analysis as formatted text.

        Args:
            analysis: ImpactAnalysis object

        Returns:
            Formatted impact analysis text
        """
        lines = []

        lines.append(self._format_section("IMPACT ANALYSIS", Color.BLUE))
        lines.append("")

        # Overview
        lines.append(f"  Total Changes: {self._colorize(str(analysis.total_changes), Color.BOLD)}")
        lines.append(f"  Affected Linear Issues: {self._colorize(str(analysis.affected_issues), Color.BOLD)}")
        lines.append(f"  Estimated API Calls: {self._colorize(str(analysis.estimated_api_calls), Color.BOLD)}")
        lines.append("")

        # State transitions
        if analysis.state_transitions:
            lines.append(f"  {self._colorize('State Transitions:', Color.BOLD)}")
            for content_key, from_state, to_state in analysis.state_transitions:
                transition = f"{from_state} → {to_state}"
                lines.append(f"    • {content_key}: {self._colorize(transition, Color.YELLOW)}")
            lines.append("")

        # Risk summary
        lines.append(f"  {self._colorize('Risk Assessment:', Color.BOLD)}")
        high_count = analysis.risk_summary.get('high', 0)
        med_count = analysis.risk_summary.get('medium', 0)
        low_count = analysis.risk_summary.get('low', 0)

        if high_count > 0:
            lines.append(f"    {self._colorize('⚠', Color.RED)} High Risk: {high_count}")
        if med_count > 0:
            lines.append(f"    {self._colorize('!', Color.YELLOW)} Medium Risk: {med_count}")
        if low_count > 0:
            lines.append(f"    {self._colorize('✓', Color.GREEN)} Low Risk: {low_count}")
        lines.append("")

        # Dependencies (show if any exist)
        if analysis.dependencies:
            dep_count = sum(len(deps) for deps in analysis.dependencies.values())
            lines.append(f"  {self._colorize('Dependencies:', Color.BOLD)} {dep_count} relationships detected")
            lines.append("")

        return "\n".join(lines)


def generate_preview(operations: List[SyncOperation],
                    previous_index: Optional[Dict[str, Any]] = None,
                    current_index: Optional[Dict[str, Any]] = None,
                    colored: bool = True,
                    detailed: bool = False,
                    show_impact: bool = True) -> str:
    """
    Generate preview for sync operations (convenience function).

    Args:
        operations: List of sync operations
        previous_index: Previous content index (optional)
        current_index: Current content index (optional)
        colored: Whether to use ANSI colors
        detailed: Include detailed diffs
        show_impact: Include impact analysis

    Returns:
        Formatted preview text
    """
    generator = PreviewGenerator(colored=colored)
    items = generator.generate_preview(operations, previous_index, current_index)
    return generator.render_preview(items, detailed=detailed, show_impact=show_impact,
                                   previous_index=previous_index, current_index=current_index)


def preview_content_updates(updates: List[ContentUpdate], colored: bool = True) -> str:
    """
    Generate preview for content updates with field-level changes.

    Args:
        updates: List of ContentUpdate objects
        colored: Whether to use ANSI colors

    Returns:
        Formatted preview text
    """
    lines = []
    color = Color if colored else type('Color', (), {attr: '' for attr in dir(Color) if not attr.startswith('_')})()

    # Header
    lines.append(f"{color.BOLD}═══════════════════════════════════════════════════════════════{color.RESET}")
    lines.append(f"{color.BOLD}{color.CYAN}CONTENT UPDATE PREVIEW{color.RESET}")
    lines.append(f"{color.BOLD}═══════════════════════════════════════════════════════════════{color.RESET}")
    lines.append("")

    # Summary
    total_updates = len(updates)
    by_type = {}
    for update in updates:
        by_type[update.update_type] = by_type.get(update.update_type, 0) + 1

    lines.append(f"{color.BOLD}SUMMARY{color.RESET}")
    lines.append(f"  Total Updates: {total_updates}")
    for update_type, count in by_type.items():
        lines.append(f"    - {update_type}: {count}")
    lines.append("")

    # Individual updates
    lines.append(f"{color.BOLD}CHANGES{color.RESET}")
    lines.append("")

    for update in updates:
        # Update header
        icon = "🔄" if update.update_type != "renumbering_required" else "🔢"
        lines.append(f"{icon} {color.BOLD}{update.content_key}{color.RESET}")
        lines.append(f"   Type: {color.YELLOW}{update.update_type}{color.RESET}")

        if update.requires_renumbering:
            lines.append(f"   {color.RED}⚠️  Requires Renumbering{color.RESET}")

        lines.append(f"   Fields Changed: {len(update.field_changes)}")

        # Field-level changes
        for fc in update.field_changes:
            change_color = {
                'added': color.GREEN,
                'modified': color.YELLOW,
                'deleted': color.RED
            }.get(fc.change_type, '')

            lines.append(f"     {change_color}• {fc.field_name} ({fc.change_type}){color.RESET}")

            if fc.change_type == 'modified':
                old_str = str(fc.old_value)[:60] if fc.old_value else ''
                new_str = str(fc.new_value)[:60] if fc.new_value else ''
                lines.append(f"       {color.DIM}From: {old_str}{color.RESET}")
                lines.append(f"       {color.DIM}To:   {new_str}{color.RESET}")

        lines.append("")

    # Footer
    lines.append(f"{color.BOLD}═══════════════════════════════════════════════════════════════{color.RESET}")

    return "\n".join(lines)


def preview_renumbering(mappings: List[RenumberMapping], colored: bool = True) -> str:
    """
    Generate preview for renumbering operations.

    Args:
        mappings: List of RenumberMapping objects
        colored: Whether to use ANSI colors

    Returns:
        Formatted preview text
    """
    lines = []
    color = Color if colored else type('Color', (), {attr: '' for attr in dir(Color) if not attr.startswith('_')})()

    # Header
    lines.append(f"{color.BOLD}═══════════════════════════════════════════════════════════════{color.RESET}")
    lines.append(f"{color.BOLD}{color.CYAN}RENUMBERING PREVIEW{color.RESET}")
    lines.append(f"{color.BOLD}═══════════════════════════════════════════════════════════════{color.RESET}")
    lines.append("")

    # Summary
    lines.append(f"{color.BOLD}SUMMARY{color.RESET}")
    lines.append(f"  Total Stories to Renumber: {len(mappings)}")

    epics_affected = set(m.new_epic for m in mappings)
    lines.append(f"  Epics Affected: {len(epics_affected)}")

    with_linear = sum(1 for m in mappings if m.linear_issue_id)
    lines.append(f"  Linear Issues to Update: {with_linear}")
    lines.append("")

    # Renumbering details
    lines.append(f"{color.BOLD}RENUMBERING OPERATIONS{color.RESET}")
    lines.append("")

    for mapping in mappings:
        lines.append(f"{color.YELLOW}🔢 {mapping.old_key}{color.RESET}")
        lines.append(f"   {color.DIM}From:{color.RESET} Epic {mapping.old_epic}, Story {mapping.old_story}")
        lines.append(f"   {color.GREEN}To:{color.RESET}   Epic {mapping.new_epic}, Story {mapping.new_story}")

        if mapping.linear_issue_id:
            lines.append(f"   Linear: {color.CYAN}{mapping.linear_issue_id}{color.RESET}")

        lines.append(f"   Reason: {mapping.reason}")
        lines.append("")

    # Impact warning
    lines.append(f"{color.BOLD}{color.RED}⚠️  IMPACT WARNING{color.RESET}")
    lines.append("  This operation will:")
    lines.append("    1. Update story file names and content")
    lines.append("    2. Update cross-references in other stories")
    lines.append("    3. Update Linear issues (if synced)")
    lines.append("    4. Record mappings in number registry")
    lines.append("")

    # Footer
    lines.append(f"{color.BOLD}═══════════════════════════════════════════════════════════════{color.RESET}")

    return "\n".join(lines)


def preview_update_with_confirmation(
    updates: List[ContentUpdate],
    renumber_mappings: Optional[List[RenumberMapping]] = None,
    colored: bool = True
) -> Tuple[str, bool]:
    """
    Generate comprehensive preview and request confirmation.

    Args:
        updates: List of ContentUpdate objects
        renumber_mappings: Optional list of RenumberMapping objects
        colored: Whether to use ANSI colors

    Returns:
        Tuple of (preview_text, requires_confirmation)
    """
    preview_parts = []

    # Content updates preview
    if updates:
        preview_parts.append(preview_content_updates(updates, colored))

    # Renumbering preview
    if renumber_mappings:
        preview_parts.append("")
        preview_parts.append(preview_renumbering(renumber_mappings, colored))

    preview_text = "\n".join(preview_parts)

    # Determine if confirmation required
    requires_confirmation = bool(renumber_mappings) or any(
        u.update_type in ['structural_update', 'renumbering_required']
        for u in updates
    )

    return preview_text, requires_confirmation
