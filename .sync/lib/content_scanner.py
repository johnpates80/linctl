#!/usr/bin/env python3
"""
Lightweight file discovery utilities for BMAD content.

Implements minimal surface required by tests:
- ContentScanner.find_epic_files()
- ContentScanner.find_story_files()

Patterns supported:
- Epics:  epics.md, epic-*.md, epic-*/index.md
- Stories: stories/*.md, stories/*/*.md
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


class ScannerError(Exception):
    """Errors raised during scanning operations."""


@dataclass
class ContentScanner:
    root: Path

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _ensure_root(self) -> None:
        if not self.root.exists():
            raise ScannerError(f"Root path does not exist: {self.root}")

    def find_epic_files(self) -> List[Path]:
        """Return epic file paths under root matching common patterns."""
        self._ensure_root()
        candidates: List[Path] = []

        patterns = [
            "epics.md",
            "epic-*.md",
            "epic-*/index.md",
            "epics/*.md",
            "epics/*/index.md",
        ]

        for pattern in patterns:
            candidates.extend(self.root.glob(pattern))

        # De-duplicate while preserving order
        seen = set()
        unique: List[Path] = []
        for p in candidates:
            if p not in seen:
                unique.append(p)
                seen.add(p)
        return unique

    def find_story_files(self) -> List[Path]:
        """Return story file paths under root.

        Supports direct stories directory and a nested level.
        Only returns files that look like real stories by name pattern
        "<epic>-<story>-<slug>.md". Filters out validation reports and others.
        """
        self._ensure_root()
        candidates: List[Path] = []
        patterns = [
            "stories/*.md",
            "stories/*/*.md",
        ]
        for pattern in patterns:
            candidates.extend(self.root.glob(pattern))

        # Keep only files matching the canonical story filename pattern
        # e.g., "1-2-something.md" (lowercase slug)
        import re
        rx = re.compile(r"^\d+-\d+-[a-z0-9-]+\.md$")
        result = sorted({
            p for p in candidates
            if (
                p.is_file()
                and rx.match(p.name) is not None
                and not p.name.endswith("-context.md")  # skip context companion files
            )
        })
        return result
