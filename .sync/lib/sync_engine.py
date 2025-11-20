#!/usr/bin/env python3
"""
Sync Engine for BMAD ↔ Linear

Builds a queue of create/update operations from BMAD content changes,
writes a sync report, and (optionally) applies changes via linctl.

Design goals:
- Pure-Python, stdlib only (fits project constraints)
- Safe by default (dry-run unless explicitly applied)
- Integrates with existing discovery/state/logger utilities in .sync/lib
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Tuple

# Local libs (tests add .sync/lib to sys.path)
from config_loader import SyncConfig, load_config
from content_discovery import ContentDiscovery
from content_updater import ContentUpdater, ContentUpdate
from state_manager import StateManager
from logger import get_logger
from state_mapper import get_state_mapper
from linctl_wrapper import get_wrapper, LinctlError
from validator import validate_issue_create_payload, validate_issue_update_payload
from project_selector import get_project_selector
from renumber_engine import RenumberEngine, RenumberMapping


@dataclass
class SyncOperation:
    action: str  # 'create' | 'update'
    content_key: str  # e.g., '1-4-basic-synchronization-operations' or 'epic-1'
    content_type: str  # 'story' | 'epic' | 'sprint-status'
    reason: str  # 'added' | 'modified'
    title: Optional[str] = None
    previous_hash: Optional[str] = None
    current_hash: Optional[str] = None
    issue_id: Optional[str] = None  # Linear issue ID if known
    state: Optional[str] = None  # Linear state (mapped from BMAD)
    project: Optional[str] = None  # Linear project name or ID
    team: Optional[str] = None  # Linear team key/name
    labels: Optional[list] = None  # Label intents (best-effort)


class SyncEngine:
    """Compute and apply sync operations for BMAD content."""

    def __init__(
        self,
        config: Optional[SyncConfig] = None,
        state_dir: Optional[Path] = None,
        dry_run: bool = True,
        wrapper=None,
        create_only: bool = False,
        update_only: bool = False,
    ) -> None:
        self.config = config or load_config()
        self.dry_run = dry_run
        self.create_only = create_only
        self.update_only = update_only

        # Resolve directories
        self.sync_root = Path(self.config.get("project.bmad_root"))
        self.docs_bmad = Path(self.config.get("project.docs_bmad"))
        self.state_dir = Path(state_dir) if state_dir else Path(".sync/state")

        # Utilities
        self.state = StateManager(self.state_dir)
        self.logger = get_logger()
        self.mapper = get_state_mapper()
        self.discovery = ContentDiscovery(self.docs_bmad)
        self.updater = ContentUpdater(self.state_dir)

        # Linear context
        self.team = self.config.get("linear.team_prefix") or self.config.get("linear.team_name")
        self.project = self.config.get("linear.project_name") or self.config.get("linear.project_id")
        self.wrapper = wrapper  # for testing; will fallback to get_wrapper

    # ---------- Planning ----------
    def _determine_action(self, key: str, reason: str, prev: Dict[str, Any], cur: Dict[str, Any]) -> str:
        """Choose 'create' for new content, 'update' for modified content."""
        if reason == "added":
            return "create"
        return "update"

    def _bmad_to_linear_state(self, content_state: Optional[str], content_type: str) -> Optional[str]:
        if not content_state:
            return None
        try:
            return self.mapper.bmad_to_linear(content_state, content_type=content_type)
        except Exception:
            return None

    def build_operations(
        self,
        previous_index: Optional[Dict[str, Any]],
        new_index: Dict[str, Any],
    ) -> List[SyncOperation]:
        """
        Build a list of SyncOperation from diff between previous and current index.
        Filters based on create_only/update_only flags.
        """
        ops: List[SyncOperation] = []

        # Handle stories
        prev_stories = (previous_index or {}).get("stories", {})
        cur_stories = new_index.get("stories", {})
        for key, cur_meta in cur_stories.items():
            prev_meta = prev_stories.get(key)
            if prev_meta is None:
                reason = "added"
            elif prev_meta.get("hash") != cur_meta.get("hash"):
                reason = "modified"
            else:
                continue  # unchanged

            # Check if issue exists in Linear
            linear_id = self.state.get_issue_id(key)

            # Filter based on flags
            if self.create_only and linear_id:
                continue  # Skip existing when create-only
            if self.update_only and not linear_id:
                continue  # Skip missing when update-only

            action = self._determine_action(key, reason, prev_meta or {}, cur_meta)

            # Determine context label for story
            labels = None
            try:
                st = (cur_meta.get("status") or "").strip().lower()
                if st == "ready-for-dev":
                    labels = ["Contexted"]
                elif st == "drafted":
                    labels = ["No Context"]
            except Exception:
                labels = None
            ops.append(
                SyncOperation(
                    action=action,
                    content_key=key,
                    content_type="story",
                    reason=reason,
                    title=cur_meta.get("title"),
                    previous_hash=(prev_meta or {}).get("hash"),
                    current_hash=cur_meta.get("hash"),
                    issue_id=linear_id,
                    state=self._bmad_to_linear_state(cur_meta.get("status"), content_type="story"),
                    project=self.project,
                    team=self.team,
                    labels=labels,
                )
            )

        # Handle epics (with state aggregated from sprint-status)
        prev_epics = (previous_index or {}).get("epics", {})
        cur_epics = new_index.get("epics", {})

        # Load sprint-status for epic state aggregation
        sprint_status_map: Dict[str, str] = {}
        try:
            import yaml  # type: ignore
            ss_file = self.docs_bmad / "sprint-status.yaml"
            if ss_file.exists():
                data = yaml.safe_load(ss_file.read_text(encoding="utf-8")) or {}
                sprint_status_map = (data or {}).get("development_status", {}) or {}
        except Exception:
            sprint_status_map = {}

        for key, cur_meta in cur_epics.items():
            prev_meta = prev_epics.get(key)
            if prev_meta is None:
                reason = "added"
            elif prev_meta.get("hash") != cur_meta.get("hash"):
                reason = "modified"
            else:
                continue

            # Check if issue exists in Linear
            linear_id = self.state.get_issue_id(key)

            # Filter based on flags
            if self.create_only and linear_id:
                continue  # Skip existing when create-only
            if self.update_only and not linear_id:
                continue  # Skip missing when update-only

            action = self._determine_action(key, reason, prev_meta or {}, cur_meta)

            # Compute epic BMAD state from story statuses + retrospective
            epic_bmad_state: Optional[str] = self._aggregate_epic_state(key, sprint_status_map)

            # Determine epic context label intent
            e_state = (sprint_status_map.get(key) or "").strip().lower()
            epic_labels = ["Contexted"] if e_state == "contexted" else ["No Context"]

            ops.append(
                SyncOperation(
                    action=action,
                    content_key=key,
                    content_type="epic",
                    reason=reason,
                    title=cur_meta.get("title"),
                    previous_hash=(prev_meta or {}).get("hash"),
                    current_hash=cur_meta.get("hash"),
                    issue_id=linear_id,
                    state=self._bmad_to_linear_state(epic_bmad_state, content_type="epic") if epic_bmad_state else None,
                    project=self.project,
                    team=self.team,
                    labels=epic_labels,
                )
            )

        return ops

    def _aggregate_epic_state(self, epic_key: str, sprint_status: Dict[str, str]) -> Optional[str]:
        """Aggregate BMAD epic state from story statuses and retrospective.

        Rules:
        - done: all stories are done or wont-do AND retrospective == completed
        - in-progress: any story in-progress
        - review: any story review OR (all stories done/wont-do AND retro not completed)
        - contexted/backlog: fallback to explicit epic state in sprint-status if present
        - else: backlog
        """
        try:
            if not sprint_status:
                return None
            # Extract epic number
            if not epic_key.startswith("epic-"):
                return None
            epic_num = epic_key.replace("epic-", "")
            # Collect story statuses for this epic
            story_statuses: Dict[str, str] = {
                k: v for k, v in sprint_status.items()
                if k.startswith(f"{epic_num}-") and k.count('-') >= 2
            }
            retro_status = sprint_status.get(f"epic-{epic_num}-retrospective") or ""

            values = list(story_statuses.values())
            norm = lambda s: (s or '').strip().lower()
            values_norm = [norm(s) for s in values]

            # All done (treat wont-do as done-equivalent)
            def is_done_like(s: str) -> bool:
                return s in {"done", "wont-do", "wontdo", "won't-do"}

            all_done = len(values_norm) > 0 and all(is_done_like(s) for s in values_norm)
            all_ready = len(values_norm) > 0 and all(s == "ready-for-dev" for s in values_norm)
            any_ip = any(s == "in-progress" for s in values_norm)
            any_review = any(s == "review" for s in values_norm)
            retro_completed = norm(retro_status) == "completed"

            # User rule: if epic retro is done -> epic done (override)
            if retro_completed:
                return "done"
            # If all stories are ready-for-dev -> epic is 'ready-for-dev' (maps to Todo)
            if all_ready:
                return "ready-for-dev"
            # If all stories done-like but retro not completed -> review
            if all_done and not retro_completed:
                return "review"

            # If any story is in-progress, or any story in review, or some done-like but not all -> in-progress
            any_done_like = any(is_done_like(s) for s in values_norm)
            if any_ip or any_review or (any_done_like and not all_done):
                return "in-progress"
            # If mixed states (e.g., some drafted/ready/done but not all done or all ready) -> in-progress
            if values_norm and not all_done and not all_ready:
                return "in-progress"

            # If not all ready-for-dev -> backlog (includes mixed drafted/ready, or drafted only, or no stories)
            # Warn if explicit backlog but stories progressed beyond backlog
            explicit = norm(sprint_status.get(epic_key) or "")
            if explicit == "backlog":
                progressed = any(s in {"drafted", "ready-for-dev", "in-progress", "review", "done"} for s in values_norm)
                if progressed:
                    try:
                        self.logger.warning(
                            "Epic marked backlog but stories progressed",
                            context={
                                "epic": epic_key,
                                "story_status_counts": {s: values_norm.count(s) for s in set(values_norm)},
                            },
                        )
                    except Exception:
                        pass
            return "backlog"
        except Exception:
            return None

    def ensure_project_id(self) -> Optional[str]:
        """
        Ensure project ID is available, prompting user if needed.

        Priority order:
        1. Environment: LINEAR_PROJECT
        2. Config: sync_config.yaml project_id
        3. Interactive prompt via ProjectSelector

        Returns:
            Project ID or None if not available/cancelled
        """
        # Check environment variable first
        import os
        project_id = os.environ.get('LINEAR_PROJECT')

        if not project_id:
            # Check config
            project_id = self.config.get('linear.project_id')

        if not project_id:
            # Interactive prompt
            self.logger.info("Project ID not found, prompting user...")
            selector = get_project_selector(self.team)
            project_id = selector.ensure_project_id()

            if not project_id:
                self.logger.error("Project ID required but not provided")
                return None

        return project_id

    def _add_linear_id_to_file(
        self,
        file_path: Path,
        linear_id: str,
        content_type: str
    ) -> None:
        """
        Add Linear ID marker to BMAD file.

        For epics: Add to header section after Epic ID line
        For stories: Add after Status line

        Args:
            file_path: Path to BMAD file
            linear_id: Linear issue ID (e.g., RAE-310)
            content_type: 'epic' or 'story'
        """
        if not file_path.exists():
            self.logger.warning(f"File not found for Linear ID addition: {file_path}")
            return

        try:
            content = file_path.read_text(encoding='utf-8')

            if content_type == "epic":
                # Add after "**Epic ID:**" line
                marker = f"**Linear Epic:** {linear_id}"

                # Find the Epic ID line and insert after it
                if "**Epic ID:**" in content:
                    lines = content.split('\n')
                    for i, line in enumerate(lines):
                        if "**Epic ID:**" in line:
                            # Insert after this line if not already present
                            if i + 1 < len(lines) and "**Linear Epic:**" not in lines[i + 1]:
                                lines.insert(i + 1, marker)
                                content = '\n'.join(lines)
                                break
                else:
                    # Add at the top if Epic ID not found
                    content = f"{marker}\n\n{content}"

            elif content_type == "story":
                # Add after "Status:" line
                marker = f"**Linear Issue:** {linear_id}"

                # Find Status line and insert after it
                if "Status:" in content or "**Status:**" in content:
                    lines = content.split('\n')
                    for i, line in enumerate(lines):
                        if "Status:" in line or "**Status:**" in line:
                            # Insert after this line if not already present
                            if i + 1 < len(lines) and "**Linear Issue:**" not in lines[i + 1]:
                                lines.insert(i + 1, marker)
                                content = '\n'.join(lines)
                                break
                else:
                    # Add at the top if Status not found
                    content = f"{marker}\n\n{content}"

            # Write updated content
            file_path.write_text(content, encoding='utf-8')
            self.logger.info(
                f"Added Linear ID to {file_path.name}",
                context={"linear_id": linear_id, "type": content_type}
            )

        except Exception as e:
            self.logger.error(
                f"Failed to add Linear ID to {file_path}",
                context={"error": str(e)}
            )

    def _renumber_after_create(
        self,
        op: SyncOperation,
        linear_id: str
    ) -> None:
        """
        Immediately renumber BMAD files after Linear creation.

        Steps:
        1. Extract numeric ID (strip team prefix like RAE-)
        2. Rename files
        3. Update cross-references
        4. Update registry
        5. Add Linear ID to files

        Args:
            op: SyncOperation that was just created
            linear_id: Linear issue ID (e.g., RAE-310)
        """
        try:
            # Extract numeric ID
            team_prefix = self.config.get('linear.team_prefix') or 'RAE'
            numeric_id = linear_id.replace(f"{team_prefix}-", "")

            if op.content_type == "epic":
                # Epic renumbering: epic-1-context.md → epic-310-context.md
                old_key = op.content_key  # e.g., "epic-1"
                new_key = f"epic-{numeric_id}"
                old_file = self.docs_bmad / f"{old_key}-context.md"
                new_file = self.docs_bmad / f"{new_key}-context.md"

                if old_file.exists():
                    # Rename file
                    old_file.rename(new_file)
                    self.logger.info(f"Renamed {old_file.name} → {new_file.name}")

                    # Add Linear ID to file
                    self._add_linear_id_to_file(new_file, linear_id, "epic")

                    # Update registry
                    self.state.register_issue(new_key, linear_id)

                    # Create mapping for cross-reference updates
                    old_epic_num = int(old_key.replace("epic-", ""))
                    mapping = RenumberMapping(
                        old_key=old_key,
                        new_key=new_key,
                        old_epic=old_epic_num,
                        old_story=0,
                        new_epic=int(numeric_id),
                        new_story=0,
                        linear_issue_id=linear_id,
                        timestamp=datetime.now().isoformat()
                    )

                    # Update cross-references
                    renumber_engine = RenumberEngine(
                        state_dir=self.state_dir,
                        docs_bmad=self.docs_bmad
                    )
                    renumber_engine.update_cross_references(mapping, self.docs_bmad)
                    renumber_engine.record_mapping(mapping)

            elif op.content_type == "story":
                # Story renumbering: 1-1-story-name.md → 310-311-story-name.md
                # Parse old key: "1-1-story-name"
                parts = op.content_key.split("-", 2)
                if len(parts) < 2:
                    self.logger.error(f"Invalid story key format: {op.content_key}")
                    return

                old_epic = parts[0]
                old_story = parts[1]
                story_name = parts[2] if len(parts) > 2 else ""

                # Get epic's Linear ID to determine epic number
                epic_key = f"epic-{old_epic}"
                epic_linear_id = self.state.get_issue_id(epic_key)

                if epic_linear_id:
                    # Use epic's Linear ID for consistent numbering
                    epic_numeric = epic_linear_id.replace(f"{team_prefix}-", "")
                else:
                    # Epic not yet created, use old epic number
                    epic_numeric = old_epic

                # New key: "310-311-story-name"
                new_key = f"{epic_numeric}-{numeric_id}"
                if story_name:
                    new_key += f"-{story_name}"

                old_file = self.docs_bmad / "stories" / f"{op.content_key}.md"
                new_file = self.docs_bmad / "stories" / f"{new_key}.md"

                if old_file.exists():
                    # Rename file
                    old_file.rename(new_file)
                    self.logger.info(f"Renamed {old_file.name} → {new_file.name}")

                    # Add Linear ID to file
                    self._add_linear_id_to_file(new_file, linear_id, "story")

                    # Update registry
                    self.state.register_issue(new_key, linear_id)

                    # Create mapping for cross-reference updates
                    mapping = RenumberMapping(
                        old_key=op.content_key,
                        new_key=new_key,
                        old_epic=int(old_epic),
                        old_story=int(old_story),
                        new_epic=int(epic_numeric),
                        new_story=int(numeric_id),
                        linear_issue_id=linear_id,
                        timestamp=datetime.now().isoformat()
                    )

                    # Update cross-references
                    renumber_engine = RenumberEngine(
                        state_dir=self.state_dir,
                        docs_bmad=self.docs_bmad
                    )
                    renumber_engine.update_cross_references(mapping, self.docs_bmad)
                    renumber_engine.record_mapping(mapping)

                    # Update sprint-status.yaml
                    self._update_sprint_status_key(op.content_key, new_key)

        except Exception as e:
            self.logger.error(
                f"Failed to renumber after create: {op.content_key}",
                context={"error": str(e), "linear_id": linear_id}
            )

    def _update_sprint_status_key(
        self,
        old_key: str,
        new_key: str
    ) -> None:
        """
        Update story key in sprint-status.yaml.

        Args:
            old_key: Old story key (e.g., "1-1-story-name")
            new_key: New story key (e.g., "310-311-story-name")
        """
        try:
            sprint_status_file = self.docs_bmad / "sprint-status.yaml"

            if not sprint_status_file.exists():
                return

            import yaml

            content = sprint_status_file.read_text(encoding='utf-8')
            config = yaml.safe_load(content)

            if not config or 'stories' not in config:
                return

            # Update story key if found
            stories = config.get('stories', {})
            if old_key in stories:
                stories[new_key] = stories.pop(old_key)

                # Write back
                sprint_status_file.write_text(
                    yaml.dump(config, default_flow_style=False),
                    encoding='utf-8'
                )

                self.logger.info(
                    f"Updated sprint-status.yaml: {old_key} → {new_key}"
                )

        except Exception as e:
            self.logger.error(
                f"Failed to update sprint-status.yaml",
                context={"error": str(e)}
            )

    def _preserve_comments_via_note(
        self,
        content_update: ContentUpdate,
        issue_id: str
    ) -> Optional[str]:
        """
        Create a preservation note for comments when updating an issue.

        Note: This creates a comment documenting the sync update.
        Full comment preservation requires Linear API/MCP access.

        Args:
            content_update: ContentUpdate with change details
            issue_id: Linear issue ID

        Returns:
            Comment text to add, or None if not needed
        """
        if not content_update.field_changes:
            return None

        # Build sync update note
        lines = [
            "**BMAD Sync Update**",
            "",
            f"Updated {len(content_update.field_changes)} field(s) from BMAD:"
        ]

        for fc in content_update.field_changes:
            change_desc = f"{fc.change_type}: {fc.field_name}"
            if fc.change_type == 'modified':
                old_str = str(fc.old_value)[:50] if fc.old_value else ''
                new_str = str(fc.new_value)[:50] if fc.new_value else ''
                change_desc += f" (was: {old_str}...)"
            lines.append(f"  - {change_desc}")

        lines.append("")
        lines.append(f"*Update type: {content_update.update_type}*")

        return "\n".join(lines)

    def apply_smart_update(
        self,
        content_update: ContentUpdate,
        issue_id: str,
        wrapper
    ) -> Tuple[bool, str]:
        """
        Apply a smart update to a Linear issue, preserving unchanged fields.

        Args:
            content_update: ContentUpdate object with field-level changes
            issue_id: Linear issue ID
            wrapper: LinctlWrapper instance

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Fetch current Linear issue data
            existing_issue = wrapper.issue_get(issue_id)

            # Build update payload with only changed fields
            payload = {}

            for field_change in content_update.field_changes:
                field = field_change.field_name
                new_value = field_change.new_value

                # Map BMAD fields to Linear fields
                if field == 'title':
                    # Note: linctl doesn't support title updates yet
                    # This would require Linear API or MCP
                    self.logger.warning(
                        f"Title change detected but linctl doesn't support title updates: {issue_id}",
                        context={"old": field_change.old_value, "new": new_value}
                    )
                elif field == 'description':
                    payload['description'] = new_value or ''
                elif field == 'status':
                    # Map BMAD status to Linear state
                    linear_state = self.mapper.bmad_to_linear(new_value, content_type='story')
                    if linear_state:
                        payload['state'] = linear_state
                elif field == 'priority':
                    payload['priority'] = new_value
                elif field in ['labels', 'assignee']:
                    # These would require Linear API or MCP
                    self.logger.warning(
                        f"Field '{field}' change detected but requires Linear API/MCP for updates",
                        context={"issue_id": issue_id}
                    )

            if not payload:
                return (True, f"No updatable fields changed for {issue_id}")

            # Validate payload
            allowed_states = list(self.mapper.config.get('story_states', {}).get('bmad_to_linear', {}).values())
            v_errors = validate_issue_update_payload(payload, allowed_states)
            if v_errors:
                return (False, f"Invalid update payload: {', '.join(v_errors)}")

            # Apply update
            wrapper.issue_update(issue_id, payload)

            # Log successful update
            updated_fields = list(payload.keys())
            self.logger.info(
                f"Updated {issue_id} for {content_update.content_key}",
                context={
                    "fields": updated_fields,
                    "update_type": content_update.update_type
                }
            )

            return (True, f"Updated {len(updated_fields)} fields in {issue_id}")

        except LinctlError as e:
            return (False, f"linctl error: {e}")
        except Exception as e:
            return (False, f"error: {e}")

    # ---------- Execution ----------
    def write_report(
        self,
        operations: List[SyncOperation],
        previous_index: Optional[Dict[str, Any]],
        new_index: Dict[str, Any],
    ) -> Path:
        """Write sync report to .sync/state/sync_report.json."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": len(operations),
                "create": sum(1 for o in operations if o.action == "create"),
                "update": sum(1 for o in operations if o.action == "update"),
            },
            "operations": [asdict(o) for o in operations],
            "previous_index_hash": (previous_index or {}).get("sprint_status_hash"),
            "new_index_hash": new_index.get("sprint_status_hash"),
        }

        out_file = self.state.state_dir / "sync_report.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self.logger.info(f"Sync report saved: {out_file}")
        return out_file

    def apply(self, operations: List[SyncOperation]) -> Tuple[int, int, List[str]]:
        """
        Optionally apply operations via linctl. Returns (success, failed, messages).
        """
        if self.dry_run:
            return (0, 0, ["dry_run: no operations applied"])

        wrapper = self.wrapper or get_wrapper()
        success = 0
        failed = 0
        messages: List[str] = []

        # Ensure project ID is available before creating anything
        project_id = self.ensure_project_id()
        if not project_id:
            return (0, 0, ["error: project ID required but not provided"])

        # Update project for all operations
        self.project = project_id

        # Backup state files for rollback
        backup_root = self.state.backup_dir / f"pre-sync-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        backup_root.mkdir(parents=True, exist_ok=True)
        for f in [self.state.content_index_file, self.state.sync_state_file, self.state.number_registry_file]:
            if f.exists():
                shutil.copy2(f, backup_root / f.name)

        total = len(operations)
        for i, op in enumerate(operations, start=1):
            # Live progress output
            try:
                print(f"Syncing {i}/{total}: {op.content_type} {op.content_key} [{op.action}]")
            except Exception:
                pass
            try:
                if op.action == "create":
                    # Prefix title with emoji based on content type
                    if op.content_type == "epic":
                        title_str = f"\U0001F4E6 EPIC: {op.title or op.content_key}"
                    elif op.content_type == "story":
                        title_str = f"\U0001F4CB STORY: {op.title or op.content_key}"
                    else:
                        title_str = op.title or op.content_key

                    payload = {
                        "title": title_str,
                        "team": op.team or "",
                        "project": self.project or "",
                    }

                    # Validate minimal create payload (no state on create)
                    # Select allowed states set per content type for validation helper (if needed)
                    allowed_states_map = self.mapper.config.get(
                        'story_states' if op.content_type == 'story' else 'epic_states', {}
                    )
                    allowed_states = list((allowed_states_map.get('bmad_to_linear', {}) or {}).values())
                    v_errors = validate_issue_create_payload(payload, allowed_states)
                    if v_errors:
                        raise ValueError(f"invalid create payload for {op.content_key}: {', '.join(v_errors)}")

                    # Pass labels on create if present
                    if op.labels:
                        payload['labels'] = op.labels
                    result = wrapper.issue_create(payload)
                    # Prefer human identifier (RAE-123) for subsequent updates; keep uuid as fallback
                    issue_key = (
                        result.get("key")
                        or result.get("identifier")
                        or result.get("issue", {}).get("key")
                        or result.get("issue", {}).get("identifier")
                    )
                    issue_uuid = (
                        result.get("id")
                        or result.get("uuid")
                        or result.get("issue", {}).get("id")
                    )
                    issue_id = issue_key or issue_uuid
                    if issue_id:
                        # Register with old key first (before renumbering)
                        self.state.register_issue(op.content_key, str(issue_id))
                        # After creation, apply state update for stories (linctl create lacks --state)
                        # Apply mapped state after create (prefer key, fallback to uuid)
                        if op.content_type in ("story", "epic") and op.state:
                            allowed_states_map_u = self.mapper.config.get('story_states' if op.content_type == 'story' else 'epic_states', {})
                            allowed_states_u = list((allowed_states_map_u.get('bmad_to_linear', {}) or {}).values())
                            v_errors_u = validate_issue_update_payload({"state": op.state}, allowed_states_u)
                            if v_errors_u:
                                raise ValueError(f"invalid update payload for {op.content_key}: {', '.join(v_errors_u)}")
                            # Try with key first, then uuid
                            update_ok = False
                            try:
                                if issue_key:
                                    wrapper.issue_update(str(issue_key), {"state": op.state})
                                    update_ok = True
                            except Exception:
                                update_ok = False
                            if not update_ok and issue_uuid:
                                try:
                                    wrapper.issue_update(str(issue_uuid), {"state": op.state})
                                    update_ok = True
                                except Exception:
                                    update_ok = False

                        # Immediately renumber BMAD files to match Linear ID
                        self._renumber_after_create(op, str(issue_id))

                    # Labels set on create above; nothing further needed

                    success += 1
                    messages.append(f"created {op.content_type} {issue_id} for {op.content_key}")
                elif op.action == "update" and op.issue_id:
                    payload = {}
                    if op.state:
                        payload["state"] = op.state
                    # Validate payload before update (per content type)
                    allowed_states_map = self.mapper.config.get(
                        'story_states' if op.content_type == 'story' else 'epic_states', {}
                    )
                    allowed_states = list((allowed_states_map.get('bmad_to_linear', {}) or {}).values())
                    v_errors = validate_issue_update_payload(payload, allowed_states)
                    if v_errors:
                        raise ValueError(f"invalid update payload for {op.content_key}: {', '.join(v_errors)}")
                    # Add label updates when appropriate (prefer add/remove to avoid clobber)
                    if op.labels:
                        add_labels = list({l for l in (op.labels or []) if l})
                        remove_labels: List[str] = []
                        # Keep Contexted/No Context mutually exclusive
                        if 'Contexted' in add_labels and 'No Context' not in remove_labels:
                            remove_labels.append('No Context')
                        if 'No Context' in add_labels and 'Contexted' not in remove_labels:
                            remove_labels.append('Contexted')
                        payload['add_labels'] = add_labels
                        payload['remove_labels'] = remove_labels

                    wrapper.issue_update(op.issue_id, payload)
                    # Ensure registry is aware of mapping for conflict checks
                    self.state.register_issue(op.content_key, str(op.issue_id))

                    # Best-effort: apply label intents on update
                    try:
                        if op.labels:
                            self._apply_labels_intent(str(op.issue_id), op.labels)
                    except Exception:
                        pass
                    success += 1
                    messages.append(f"updated {op.issue_id} for {op.content_key}")
                else:
                    messages.append(f"planned update, missing issue_id: {op.content_key}")
            except LinctlError as e:
                failed += 1
                messages.append(f"linctl error for {op.content_key}: {e}")
            except Exception as e:
                failed += 1
                messages.append(f"error for {op.content_key}: {e}")

        # Rollback on any failure
        if failed > 0:
            for f in [self.state.content_index_file, self.state.sync_state_file, self.state.number_registry_file]:
                backup_file = backup_root / f.name
                if backup_file.exists():
                    shutil.copy2(backup_file, f)
            messages.append("rollback: restored state from pre-sync backup due to failures")

        return success, failed, messages

    def _apply_labels_intent(self, issue_id: str, labels: List[str]) -> None:
        # Deprecated: labels now applied via linctl flags in update/create
        try:
            self.logger.debug("labels applied", context={"issue": issue_id, "labels": labels})
        except Exception:
            pass

    def detect_and_record_conflicts(self, index: Dict[str, Any]) -> List[str]:
        """Detect conflicts by comparing BMAD/Linear states and record them.

        Returns a list of content_keys that have conflicts.
        """
        wrapper = self.wrapper or get_wrapper()
        conflicts: List[str] = []

        # Last sync timestamp
        sync_state = self.state.get_sync_state()
        last_sync = sync_state.get("last_sync")

        if not last_sync:
            return conflicts

        stories = index.get("stories", {})
        for key, meta in stories.items():
            issue_id = self.state.get_issue_id(key)
            if not issue_id:
                continue

            # Fetch Linear issue to get state + updatedAt
            try:
                issue = wrapper.issue_get(issue_id)
            except Exception:
                continue

            linear_state = issue.get("state") or issue.get("state", {}).get("name") or ""
            linear_updated = issue.get("updatedAt") or issue.get("updated_at") or ""
            bmad_state = meta.get("status") or ""
            bmad_updated = meta.get("last_modified") or ""

            if not (linear_state and linear_updated and bmad_state and bmad_updated):
                continue

            conflict = self.mapper.detect_conflict(
                content_key=key,
                bmad_state=bmad_state,
                bmad_updated=bmad_updated,
                linear_state=linear_state,
                linear_updated=linear_updated,
                last_sync=last_sync,
            )
            if conflict:
                self.mapper.save_conflict(conflict)
                conflicts.append(key)

        return conflicts

    # ---------- Orchestration ----------
    def sync(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Run discovery, build operations, write report, and return plan."""
        # Load previous index from state file if present
        previous_index = None
        try:
            if not force_refresh and self.state.content_index_file.exists():
                previous_index = json.loads(self.state.content_index_file.read_text())
        except Exception:
            previous_index = None

        # Discover current index and diff
        new_index = self.discovery.discover_all(previous_index)

        # Plan
        operations = self.build_operations(previous_index, new_index)

        # Report
        report_path = self.write_report(operations, previous_index, new_index)

        return {
            "operations": operations,
            "report": str(report_path),
            "summary": {
                "total": len(operations),
                "create": sum(1 for o in operations if o.action == "create"),
                "update": sum(1 for o in operations if o.action == "update"),
            },
            "previous_index": previous_index,
            "current_index": new_index,
        }


if __name__ == "__main__":
    # Simple manual run helper
    engine = SyncEngine(dry_run=True)
    plan = engine.sync()
    print(json.dumps({"summary": plan["summary"], "report": plan["report"]}, indent=2))
