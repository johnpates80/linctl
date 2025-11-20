#!/usr/bin/env python3
"""
Three-Way Merge Algorithm for Complex Conflicts.

Implements three-way merge with common ancestor detection
for resolving multi-way conflicts between BMAD, Linear, and historical states.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from logger import get_logger


@dataclass
class ThreeWayConflict:
    """Represents a three-way conflict."""
    conflict_id: str
    content_key: str
    bmad_state: str
    linear_state: str
    ancestor_state: Optional[str]
    bmad_updated: str
    linear_updated: str
    ancestor_updated: Optional[str]
    conflict_type: str = "three-way"


@dataclass
class MergeVisualization:
    """Visualization of three-way merge."""
    bmad_version: Dict[str, Any]
    linear_version: Dict[str, Any]
    ancestor_version: Optional[Dict[str, Any]]
    diff_bmad_ancestor: List[str]
    diff_linear_ancestor: List[str]
    diff_bmad_linear: List[str]
    merge_recommendation: str
    confidence: float


class ThreeWayMerge:
    """Three-way merge algorithm implementation."""

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize three-way merge.

        Args:
            state_dir: State directory for history
        """
        self.logger = get_logger()
        self.state_dir = state_dir or Path('.sync/state')

    def find_common_ancestor(
        self,
        content_key: str,
        bmad_state: str,
        linear_state: str,
        history: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Find common ancestor state from history.

        Args:
            content_key: Content key
            bmad_state: Current BMAD state
            linear_state: Current Linear state
            history: List of historical state changes

        Returns:
            Common ancestor state or None
        """
        # Filter history for this content key
        relevant_history = [
            h for h in history
            if h.get('content_key') == content_key
        ]

        if not relevant_history:
            return None

        # Sort by timestamp (oldest first)
        relevant_history.sort(key=lambda h: h.get('timestamp', ''))

        # Find last state where both BMAD and Linear agreed
        for entry in reversed(relevant_history):
            entry_state = entry.get('state', '')
            # Check if this state preceded both current states
            if entry_state != bmad_state and entry_state != linear_state:
                # Found a divergence point - this is likely the ancestor
                return entry

        # If no clear ancestor, use the oldest state
        if relevant_history:
            return relevant_history[0]

        return None

    def create_three_way_conflict(
        self,
        content_key: str,
        bmad_state: str,
        linear_state: str,
        bmad_updated: str,
        linear_updated: str,
        history: List[Dict[str, Any]]
    ) -> ThreeWayConflict:
        """
        Create a three-way conflict with ancestor detection.

        Args:
            content_key: Content key
            bmad_state: Current BMAD state
            linear_state: Current Linear state
            bmad_updated: BMAD timestamp
            linear_updated: Linear timestamp
            history: Historical state changes

        Returns:
            ThreeWayConflict with ancestor info
        """
        # Find common ancestor
        ancestor = self.find_common_ancestor(
            content_key,
            bmad_state,
            linear_state,
            history
        )

        ancestor_state = ancestor.get('state') if ancestor else None
        ancestor_updated = ancestor.get('timestamp') if ancestor else None

        conflict_id = f"3way-{content_key}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        return ThreeWayConflict(
            conflict_id=conflict_id,
            content_key=content_key,
            bmad_state=bmad_state,
            linear_state=linear_state,
            ancestor_state=ancestor_state,
            bmad_updated=bmad_updated,
            linear_updated=linear_updated,
            ancestor_updated=ancestor_updated
        )

    def visualize_three_way(
        self,
        conflict: ThreeWayConflict
    ) -> MergeVisualization:
        """
        Create visualization of three-way conflict.

        Args:
            conflict: Three-way conflict

        Returns:
            MergeVisualization with diffs
        """
        # Build version representations
        bmad_version = {
            'state': conflict.bmad_state,
            'updated': conflict.bmad_updated,
            'source': 'BMAD'
        }

        linear_version = {
            'state': conflict.linear_state,
            'updated': conflict.linear_updated,
            'source': 'Linear'
        }

        ancestor_version = None
        if conflict.ancestor_state:
            ancestor_version = {
                'state': conflict.ancestor_state,
                'updated': conflict.ancestor_updated,
                'source': 'Common Ancestor'
            }

        # Generate diffs
        diff_bmad_linear = self._generate_diff(
            conflict.bmad_state,
            conflict.linear_state,
            'BMAD',
            'Linear'
        )

        diff_bmad_ancestor = []
        diff_linear_ancestor = []
        if conflict.ancestor_state:
            diff_bmad_ancestor = self._generate_diff(
                conflict.ancestor_state,
                conflict.bmad_state,
                'Ancestor',
                'BMAD'
            )
            diff_linear_ancestor = self._generate_diff(
                conflict.ancestor_state,
                conflict.linear_state,
                'Ancestor',
                'Linear'
            )

        # Generate merge recommendation
        recommendation, confidence = self._recommend_three_way_resolution(conflict)

        return MergeVisualization(
            bmad_version=bmad_version,
            linear_version=linear_version,
            ancestor_version=ancestor_version,
            diff_bmad_ancestor=diff_bmad_ancestor,
            diff_linear_ancestor=diff_linear_ancestor,
            diff_bmad_linear=diff_bmad_linear,
            merge_recommendation=recommendation,
            confidence=confidence
        )

    def _generate_diff(
        self,
        from_text: str,
        to_text: str,
        from_label: str,
        to_label: str
    ) -> List[str]:
        """Generate unified diff between two texts."""
        diff = difflib.unified_diff(
            [from_text],
            [to_text],
            fromfile=from_label,
            tofile=to_label,
            lineterm=''
        )
        return list(diff)

    def _recommend_three_way_resolution(
        self,
        conflict: ThreeWayConflict
    ) -> Tuple[str, float]:
        """
        Recommend resolution for three-way conflict.

        Args:
            conflict: Three-way conflict

        Returns:
            Tuple of (recommendation, confidence)
        """
        if not conflict.ancestor_state:
            # No ancestor - fall back to two-way merge
            return "intelligent-merge (no ancestor available)", 0.5

        # Check if one side matches ancestor (other side has exclusive changes)
        if conflict.bmad_state == conflict.ancestor_state:
            # BMAD unchanged, Linear has changes
            return "keep-linear (BMAD unchanged since ancestor)", 0.9

        if conflict.linear_state == conflict.ancestor_state:
            # Linear unchanged, BMAD has changes
            return "keep-bmad (Linear unchanged since ancestor)", 0.9

        # Both changed - check timestamps
        bmad_time = datetime.fromisoformat(conflict.bmad_updated.replace('Z', '+00:00'))
        linear_time = datetime.fromisoformat(conflict.linear_updated.replace('Z', '+00:00'))

        if bmad_time > linear_time:
            return "keep-bmad (more recent changes)", 0.7
        else:
            return "keep-linear (more recent changes)", 0.7

    def format_visualization(self, viz: MergeVisualization) -> str:
        """
        Format three-way visualization for display.

        Args:
            viz: Merge visualization

        Returns:
            Formatted string
        """
        lines = []
        lines.append("=" * 100)
        lines.append("THREE-WAY MERGE VISUALIZATION")
        lines.append("=" * 100)
        lines.append("")

        # Three-column comparison
        if viz.ancestor_version:
            lines.append("╔═══════════════════════════════╦═══════════════════════════════╦═══════════════════════════════╗")
            lines.append("║        BMAD (Ours)            ║     Common Ancestor (Base)    ║      Linear (Theirs)          ║")
            lines.append("╠═══════════════════════════════╬═══════════════════════════════╬═══════════════════════════════╣")

            bmad_state = viz.bmad_version['state'][:27]
            ancestor_state = viz.ancestor_version['state'][:27]
            linear_state = viz.linear_version['state'][:27]

            lines.append(f"║ {bmad_state:<29} ║ {ancestor_state:<29} ║ {linear_state:<29} ║")

            bmad_time = viz.bmad_version['updated'][:27]
            ancestor_time = viz.ancestor_version['updated'][:27] if viz.ancestor_version['updated'] else 'Unknown'
            linear_time = viz.linear_version['updated'][:27]

            lines.append(f"║ {bmad_time:<29} ║ {ancestor_time:<29} ║ {linear_time:<29} ║")
            lines.append("╚═══════════════════════════════╩═══════════════════════════════╩═══════════════════════════════╝")
        else:
            # Two-way comparison fallback
            lines.append("╔═══════════════════════════════╦═══════════════════════════════╗")
            lines.append("║        BMAD (Ours)            ║      Linear (Theirs)          ║")
            lines.append("╠═══════════════════════════════╬═══════════════════════════════╣")

            bmad_state = viz.bmad_version['state'][:27]
            linear_state = viz.linear_version['state'][:27]

            lines.append(f"║ {bmad_state:<29} ║ {linear_state:<29} ║")
            lines.append("╚═══════════════════════════════╩═══════════════════════════════╝")

        lines.append("")

        # Diffs
        if viz.diff_bmad_ancestor:
            lines.append("BMAD Changes (from ancestor):")
            for line in viz.diff_bmad_ancestor[:10]:
                lines.append(f"  {line}")
            lines.append("")

        if viz.diff_linear_ancestor:
            lines.append("Linear Changes (from ancestor):")
            for line in viz.diff_linear_ancestor[:10]:
                lines.append(f"  {line}")
            lines.append("")

        # Recommendation
        lines.append("MERGE RECOMMENDATION:")
        lines.append(f"  {viz.merge_recommendation}")
        lines.append(f"  Confidence: {viz.confidence:.0%}")
        lines.append("")

        return "\n".join(lines)

    def perform_three_way_merge(
        self,
        conflict: ThreeWayConflict,
        strategy: str = "auto"
    ) -> Dict[str, Any]:
        """
        Perform three-way merge resolution.

        Args:
            conflict: Three-way conflict
            strategy: Resolution strategy ('auto', 'keep-bmad', 'keep-linear', 'ancestor')

        Returns:
            Resolved state
        """
        if strategy == "keep-bmad":
            return {
                'state': conflict.bmad_state,
                'source': 'bmad',
                'updated': conflict.bmad_updated,
                'merge_type': 'three-way',
                'resolution': 'manual-bmad'
            }

        if strategy == "keep-linear":
            return {
                'state': conflict.linear_state,
                'source': 'linear',
                'updated': conflict.linear_updated,
                'merge_type': 'three-way',
                'resolution': 'manual-linear'
            }

        if strategy == "ancestor" and conflict.ancestor_state:
            return {
                'state': conflict.ancestor_state,
                'source': 'ancestor',
                'updated': conflict.ancestor_updated,
                'merge_type': 'three-way',
                'resolution': 'revert-to-ancestor'
            }

        # Auto strategy - use recommendation
        recommendation, confidence = self._recommend_three_way_resolution(conflict)

        if "keep-bmad" in recommendation:
            use_state = conflict.bmad_state
            use_updated = conflict.bmad_updated
            use_source = 'bmad'
        elif "keep-linear" in recommendation:
            use_state = conflict.linear_state
            use_updated = conflict.linear_updated
            use_source = 'linear'
        else:
            # Default to more recent
            bmad_time = datetime.fromisoformat(conflict.bmad_updated.replace('Z', '+00:00'))
            linear_time = datetime.fromisoformat(conflict.linear_updated.replace('Z', '+00:00'))

            if bmad_time > linear_time:
                use_state = conflict.bmad_state
                use_updated = conflict.bmad_updated
                use_source = 'bmad'
            else:
                use_state = conflict.linear_state
                use_updated = conflict.linear_updated
                use_source = 'linear'

        return {
            'state': use_state,
            'source': use_source,
            'updated': use_updated,
            'merge_type': 'three-way',
            'resolution': 'auto',
            'confidence': confidence
        }


# Global three-way merge instance
_three_way_merge: Optional[ThreeWayMerge] = None


def get_three_way_merge(state_dir: Optional[Path] = None) -> ThreeWayMerge:
    """
    Get or create global three-way merge instance.

    Args:
        state_dir: State directory

    Returns:
        ThreeWayMerge instance
    """
    global _three_way_merge

    if _three_way_merge is None:
        _three_way_merge = ThreeWayMerge(state_dir=state_dir)

    return _three_way_merge
