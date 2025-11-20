#!/usr/bin/env python3
"""
Discovery orchestrator for BMAD content.

Implements minimal surface required by tests:
- ContentDiscovery.compute_hash(content: str) -> str
- ContentDiscovery.discover_all(previous_index: dict | None) -> dict

Change detection semantics for tests:
- If previous_index is None -> changes = {added: [], modified: [], deleted: []}
- When previous provided, detect file-key additions, modifications and deletions
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from content_scanner import ContentScanner
from content_parser import ContentParser
from state_manager import StateManager
from state_mapper import get_state_mapper
from linctl_wrapper import get_wrapper, LinctlError


@dataclass
class ContentDiscovery:
    root: Path

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -----------------
    # Utility functions
    # -----------------
    def normalize_content(self, content: str) -> str:
        # Normalize line endings, strip leading/trailing whitespace per line
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        normalized = "\n".join(line.strip() for line in normalized.splitlines()).strip()
        return normalized

    def compute_hash(self, content: str) -> str:
        normalized = self.normalize_content(content)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    # -----------------
    # Discovery
    # -----------------
    def _story_key_for(self, path: Path) -> str:
        return path.stem  # e.g., '1-1-test'

    def _hash_file(self, path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            text = ""
        return self.compute_hash(text)

    def _build_current_index(self) -> Dict[str, Any]:
        scanner = ContentScanner(self.root)
        epics = scanner.find_epic_files()
        stories = scanner.find_story_files()

        idx: Dict[str, Any] = {
            "last_scan": datetime.now(timezone.utc).isoformat(),
            "epics": {},
            "stories": {},
        }

        # Discover epics as normalized keys (epic-N) with titles parsed from content
        for e in epics:
            try:
                name = e.name
                # Skip the master index file to avoid duplicates
                if name == "epics.md":
                    continue
                text = e.read_text(encoding="utf-8", errors="ignore")
                import re as _re
                title = None
                epic_num = None
                # Match formats like:
                #   # Epic 2: Some Title
                #   # Epic 2 Technical Context: Some Title
                m = _re.search(r"^\s*#\s*Epic\s+(\d+)[^:]*:\s*(.+)$", text, _re.MULTILINE)
                if m:
                    epic_num = int(m.group(1))
                    title = m.group(2).strip()
                else:
                    # Fallback: "# Epic 2" on first line with no colon
                    m2 = _re.search(r"^\s*#\s*Epic\s+(\d+)\b\s*(.*)$", text, _re.MULTILINE)
                    if m2:
                        epic_num = int(m2.group(1))
                        tail = (m2.group(2) or "").strip()
                        title = tail if tail else e.stem

                if epic_num is None:
                    # Could not parse; skip this file
                    continue

                epic_key = f"epic-{epic_num}"
                idx["epics"][epic_key] = {
                    "file": str(e),
                    "hash": self._hash_file(e),
                    "title": title or e.stem,
                }
            except Exception:
                # Best-effort epic indexing; skip on parse error
                continue

        parser = ContentParser()
        for s in stories:
            key = self._story_key_for(s)
            meta = {}
            try:
                parsed = parser.parse_story_file(s)
                meta = {
                    "epic": parsed.get("epic_number"),
                    "story": parsed.get("story_number"),
                    "title": parsed.get("title"),
                    "status": parsed.get("status"),
                }
            except Exception:
                # Best-effort; still include file + hash
                meta = {}
            idx["stories"][key] = {
                "file": str(s),
                "hash": self._hash_file(s),
                **meta,
            }

        return idx

    def discover_all(self, previous_index: Dict[str, Any] | None) -> Dict[str, Any]:
        current = self._build_current_index()

        changes = {"added": [], "modified": [], "deleted": []}
        if previous_index is None:
            # Establish baseline without reporting adds on first run (per tests)
            return {**current, "changes": changes}

        prev_stories = previous_index.get("stories", {})
        curr_stories = current.get("stories", {})

        # Added
        for key in curr_stories.keys() - prev_stories.keys():
            changes["added"].append(key)

        # Deleted
        for key in prev_stories.keys() - curr_stories.keys():
            changes["deleted"].append(key)

        # Modified
        for key in curr_stories.keys() & prev_stories.keys():
            if curr_stories[key].get("hash") != prev_stories[key].get("hash"):
                changes["modified"].append(key)

        return {**current, "changes": changes}

    # -----------------
    # State helpers
    # -----------------
    def _story_meta(self, content_key: str) -> Optional[Dict[str, Any]]:
        sm = StateManager()
        try:
            idx = sm.get_content_index()
            stories = (idx or {}).get("stories", {})
            return stories.get(content_key)
        except Exception:
            return None

    def get_sync_status(self, content_key: str) -> str:
        """Compute sync status between BMAD and Linear for a content key.

        Returns one of: in_sync, bmad_ahead, linear_ahead, conflict, unknown.
        """
        meta = self._story_meta(content_key)
        if not meta:
            return "unknown"

        bmad_state = meta.get("status") or ""
        story_path = Path(meta.get("file", ""))
        try:
            bmad_updated = datetime.fromtimestamp(story_path.stat().st_mtime, tz=timezone.utc).isoformat()
        except Exception:
            bmad_updated = ""

        sm = StateManager()
        issue_id = sm.get_issue_id(content_key)
        if not issue_id:
            # No Linear mapping yet
            return "bmad_ahead" if bmad_state else "unknown"

        try:
            wrapper = get_wrapper()
            issue = wrapper.issue_get(issue_id)
            linear_state = issue.get("state") or (issue.get("state", {}) or {}).get("name") or ""
            linear_updated = issue.get("updatedAt") or issue.get("updated_at") or ""
        except (LinctlError, Exception):
            return "unknown"

        # Normalize Linear state to BMAD nomenclature
        mapper = get_state_mapper()
        has_context = story_path.with_suffix('.context.xml').exists()
        linear_as_bmad = mapper.linear_to_bmad(str(linear_state), content_type='story', context_hints={'has_context_file': has_context})

        if (bmad_state or "") == (linear_as_bmad or ""):
            return "in_sync"

        # Use last_sync window to infer who is ahead / conflict
        sync_state = sm.get_sync_state()
        last_sync = sync_state.get("last_sync")
        try:
            bmad_dt = datetime.fromisoformat((bmad_updated or "").replace('Z', '+00:00'))
            linear_dt = datetime.fromisoformat((linear_updated or "").replace('Z', '+00:00'))
            last_dt = datetime.fromisoformat((last_sync or "").replace('Z', '+00:00')) if last_sync else None
        except Exception:
            bmad_dt = linear_dt = last_dt = None

        if last_dt and bmad_dt and linear_dt:
            if bmad_dt > last_dt and linear_dt > last_dt:
                return "conflict"
            if bmad_dt > last_dt and linear_dt <= last_dt:
                return "bmad_ahead"
            if linear_dt > last_dt and bmad_dt <= last_dt:
                return "linear_ahead"

        # Fallback inference
        return "linear_ahead" if linear_state and not bmad_state else "bmad_ahead"

    def enrich_with_state_history(self, index: Dict[str, Any]) -> Dict[str, Any]:
        """Add last_state_change and history length to each story in the index."""
        stories = index.get("stories", {})
        history_path = Path('.sync/state/state_history.json')
        try:
            history = json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else {}
        except Exception:
            history = {}

        for key, meta in stories.items():
            entries = history.get(key, [])
            meta["state_history_len"] = len(entries)
            if entries:
                meta["last_state_change"] = entries[-1].get("timestamp")
            meta["state_history_path"] = str(history_path)
            # Also attach a lightweight sync status snapshot
            try:
                meta["sync_status"] = self.get_sync_status(key)
            except Exception:
                meta["sync_status"] = "unknown"

        return index

    # -----------------
    # Persistence helpers (optional)
    # -----------------
    def save_index(self, out_path: Path | str, index: Dict[str, Any]) -> None:
        """Atomically write JSON index to disk."""
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(target)
