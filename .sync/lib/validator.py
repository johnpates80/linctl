#!/usr/bin/env python3
"""
Validation utilities for BMAD content and configuration.

Provides lightweight structural validation that can run offline.
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Dict, List, Any, Iterable


def validate_sprint_status(path: str | Path = 'docs-bmad/sprint-status.yaml') -> List[str]:
    """Validate sprint-status.yaml structure.

    Checks:
    - File exists and is readable
    - Contains 'development_status:' section
    - Each non-epic key has a simple status value
    """
    errors: List[str] = []
    p = Path(path)
    if not p.exists():
        return [f"missing file: {p}"]

    text = p.read_text(encoding='utf-8', errors='ignore')
    if 'development_status:' not in text:
        errors.append("missing 'development_status:' section")

    # Very light structure checks: ensure at least one story key → status line exists
    pattern = re.compile(r"^\s*\d+-\d+-[a-z0-9-]+:\s*(backlog|drafted|ready-for-dev|in-progress|review|done)\b", re.I | re.M)
    if not pattern.search(text):
        errors.append("no story status entries found")

    return errors


def validate_story_file(path: str | Path) -> List[str]:
    """Validate structure of a story markdown file."""
    errors: List[str] = []
    p = Path(path)
    if not p.exists():
        return [f"missing file: {p}"]

    text = p.read_text(encoding='utf-8', errors='ignore')
    required_sections = [
        r"^#\s+Story\s+\d+\.\d+:",
        r"^Status:\s*(backlog|drafted|ready-for-dev|in-progress|review|done)\b",
        r"^##\s+Acceptance Criteria",
        r"^##\s+Tasks\s*/\s*Subtasks",
    ]
    for rx in required_sections:
        if not re.search(rx, text, re.I | re.M):
            errors.append(f"missing section matching: {rx}")

    return errors


def validate_epic_file(path: str | Path) -> List[str]:
    """Validate structure of an epic context markdown file."""
    errors: List[str] = []
    p = Path(path)
    if not p.exists():
        return [f"missing file: {p}"]

    text = p.read_text(encoding='utf-8', errors='ignore')
    required_sections = [
        r"^#\s*Epic\s+\d+\b",
        r"^##\s+Overview\b",
        r"^##\s+Epic\s+Goals\b",
        r"^##\s+Stories\s+Breakdown\b",
    ]
    for rx in required_sections:
        if not re.search(rx, text, re.I | re.M):
            errors.append(f"missing section matching: {rx}")

    return errors


def _glob_many(patterns: Iterable[str]) -> List[Path]:
    out: List[Path] = []
    for pat in patterns:
        out.extend(Path('.').glob(pat))
    return out


def validate_all(stories_dir: str | Path = 'docs-bmad/stories') -> Dict[str, Any]:
    """Run validations across key artifacts and return a report."""
    report: Dict[str, Any] = {
        'sprint_status': {'path': 'docs-bmad/sprint-status.yaml', 'errors': []},
        'epics': {},
        'stories': {},
        'ok': True,
    }

    ss_errors = validate_sprint_status()
    report['sprint_status']['errors'] = ss_errors
    if ss_errors:
        report['ok'] = False

    # Validate epics
    epic_errors_total = 0
    epics: Dict[str, Any] = {}
    epic_paths = _glob_many([
        'docs-bmad/epic-*.md',
        'docs-bmad/epic*/index.md',
    ])
    for ep in sorted(epic_paths):
        errs = validate_epic_file(ep)
        epics[str(ep)] = {'errors': errs}
        epic_errors_total += len(errs)
    report['epics'] = epics
    if epic_errors_total:
        report['ok'] = False

    # Validate stories
    stories: Dict[str, Any] = {}
    for p in sorted(Path(stories_dir).glob('*.md')):
        # Only validate story files named like "<epic>-<story>-<name>.md"
        if not re.match(r"^\d+-\d+-[a-z0-9-]+\.md$", p.name):
            continue
        errs = validate_story_file(p)
        stories[str(p)] = {'errors': errs}
        if errs:
            report['ok'] = False
    report['stories'] = stories

    return report


# -----------------
# Linear payload validation helpers
# -----------------

def validate_issue_create_payload(data: Dict[str, Any], allowed_states: Iterable[str]) -> List[str]:
    """Validate data for creating a Linear issue via linctl."""
    errors: List[str] = []
    title = (data or {}).get('title')
    team = (data or {}).get('team')
    state = (data or {}).get('state')

    if not title or not str(title).strip():
        errors.append("missing or empty: title")
    if not team or not str(team).strip():
        errors.append("missing or empty: team")
    if state is not None and str(state) not in set(allowed_states):
        errors.append(f"invalid state: {state}")

    return errors


def validate_issue_update_payload(data: Dict[str, Any], allowed_states: Iterable[str]) -> List[str]:
    """Validate data for updating a Linear issue via linctl."""
    errors: List[str] = []
    state = (data or {}).get('state')
    if state is not None and str(state) not in set(allowed_states):
        errors.append(f"invalid state: {state}")
    return errors


if __name__ == '__main__':
    rep = validate_all()
    print(json.dumps(rep, indent=2))
