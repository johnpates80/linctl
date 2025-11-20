#!/usr/bin/env python3
"""
Parsers for BMAD content files used in discovery and indexing.

Implements minimal surface required by tests:
- ContentParser.parse_story_file(path: Path) -> dict
- ContentParser.parse_epic_content(content: str) -> list[dict]
- ContentParser.parse_sprint_status(path: Path) -> dict
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - fallback in constrained envs
    yaml = None  # pyright: ignore[reportAssignmentType]


class ParserError(Exception):
    """Raised when parsing input fails."""


@dataclass
class ContentParser:
    """Parsers for stories, epics and sprint status files."""

    def parse_story_file(self, path: Path | str) -> Dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise ParserError(f"Story file not found: {p}")
        text = p.read_text(encoding="utf-8", errors="ignore")

        # Header: # Story N.M: Title
        header_match = re.search(r"^#\s*Story\s+(\d+)\.(\d+):\s*(.+)$", text, re.MULTILINE)
        if not header_match:
            raise ParserError("Could not parse story header '# Story N.M: Title'")
        epic_number = int(header_match.group(1))
        story_number = int(header_match.group(2))
        title = header_match.group(3).strip()

        # Status: Status: drafted
        status_match = re.search(r"^Status:\s*([A-Za-z\-]+)\s*$", text, re.MULTILINE)
        status = status_match.group(1).strip() if status_match else "drafted"

        # Acceptance Criteria section -> list
        ac: List[str] = []
        ac_section = re.search(r"^##\s*Acceptance Criteria\s*$", text, re.MULTILINE)
        if ac_section:
            start = ac_section.end()
            # Slice from AC header to next section or end
            next_section = re.search(r"^##\s+", text[start:], re.MULTILINE)
            body = text[start:] if not next_section else text[start : start + next_section.start()]
            for line in body.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Match numbered or bulleted items
                m_num = re.match(r"^\d+\.[\s]+(.+)$", line)
                m_bul = re.match(r"^[\-\*][\s]+(.+)$", line)
                if m_num:
                    ac.append(m_num.group(1).strip())
                elif m_bul:
                    ac.append(m_bul.group(1).strip())

        return {
            "epic_number": epic_number,
            "story_number": story_number,
            "title": title,
            "status": status,
            "acceptance_criteria": ac,
        }

    def parse_epic_content(self, content: str) -> List[Dict[str, Any]]:
        # Epic header: ## Epic N: Title
        epic_match = re.search(r"^##\s*Epic\s+(\d+):\s*(.+)$", content, re.MULTILINE)
        if not epic_match:
            raise ParserError("Could not parse epic header '## Epic N: Title'")
        epic_number = int(epic_match.group(1))
        title = epic_match.group(2).strip()

        # Story lines: ### Story N.M: Title
        stories = re.findall(r"^###\s*Story\s+\d+\.\d+:\s*(.+)$", content, re.MULTILINE)
        return [
            {
                "epic_number": epic_number,
                "title": title,
                "stories": [s.strip() for s in stories],
            }
        ]

    def parse_sprint_status(self, path: Path | str) -> Dict[str, str]:
        p = Path(path)
        if not p.exists():
            raise ParserError(f"Sprint status file not found: {p}")
        raw = p.read_text(encoding="utf-8", errors="ignore")

        if yaml is not None:
            data = yaml.safe_load(raw) or {}
            dev = data.get("development_status") if isinstance(data, dict) else None
            return dict(dev or {})

        # Fallback: extremely simple parser (expects exact indentation)
        result: Dict[str, str] = {}
        in_dev = False
        for line in raw.splitlines():
            if line.strip().startswith("development_status:"):
                in_dev = True
                continue
            if in_dev:
                if not line.startswith("  ") or not line.strip():
                    break
                key, _, val = line.strip().partition(":")
                result[key.strip()] = (val or "").strip()
        return result

