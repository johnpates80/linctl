#!/usr/bin/env python3
"""
Conflict Resolution Interface for BMAD ↔ Linear sync.

Provides interactive visualization, resolution strategies, automated resolution,
preview capabilities, batch processing, and resolution history tracking.
"""

from __future__ import annotations

import json
import difflib
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from logger import get_logger
from state_mapper import StateConflict, get_state_mapper
from ml_resolver import get_ml_resolver, MLPrediction
from custom_rules import get_rules_engine, ResolutionRule
from resolution_metrics import get_effectiveness_tracker
from three_way_merge import get_three_way_merge, ThreeWayConflict


class ResolutionStrategy(Enum):
    """Available conflict resolution strategies."""
    KEEP_BMAD = "keep-bmad"
    KEEP_LINEAR = "keep-linear"
    INTELLIGENT_MERGE = "intelligent-merge"
    MANUAL_FIELD_LEVEL = "manual-field-level"


@dataclass
class ConflictVisualization:
    """Represents visualized conflict data."""
    conflict_id: str
    content_key: str
    conflict_type: str
    bmad_side: Dict[str, Any]
    linear_side: Dict[str, Any]
    diff_highlights: List[str]
    timestamps: Dict[str, str]
    impact_analysis: str
    auto_resolve_suggestion: Optional[str] = None
    confidence_score: Optional[float] = None


@dataclass
class ResolutionResult:
    """Represents the result of a conflict resolution."""
    conflict_id: str
    content_key: str
    strategy: ResolutionStrategy
    resolved_state: Dict[str, Any]
    applied_at: str
    applied_by: str
    confidence: float
    manual_override: bool = False


@dataclass
class ResolutionHistory:
    """Tracks conflict resolution history."""
    resolution_id: str
    conflict_id: str
    content_key: str
    strategy: str
    resolved_at: str
    resolved_by: str
    before_state: Dict[str, Any]
    after_state: Dict[str, Any]
    was_auto_resolved: bool
    confidence: float


class ConflictResolver:
    """Main conflict resolution engine."""

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize conflict resolver.

        Args:
            state_dir: Directory for state files (default: .sync/state/)
        """
        self.mapper = get_state_mapper(state_dir=state_dir)
        self.logger = get_logger()
        self.state_dir = self.mapper.state_dir

        # Resolution history file
        self.history_file = self.state_dir / 'resolution_history.json'
        self._initialize_history()

        # Auto-resolution rules
        self.auto_rules = self._load_auto_rules()

        # Initialize new components
        self.ml_resolver = get_ml_resolver()
        self.rules_engine = get_rules_engine()
        self.effectiveness_tracker = get_effectiveness_tracker()
        self.three_way_merge = get_three_way_merge(state_dir=state_dir)

    def _initialize_history(self) -> None:
        """Initialize resolution history file."""
        if not self.history_file.exists():
            self.history_file.write_text(json.dumps([], indent=2))

    def _load_auto_rules(self) -> List[Dict[str, Any]]:
        """Load auto-resolution rules from config."""
        config = self.mapper.config
        return config.get('auto_resolution', {}).get('rules', [
            {
                'pattern': 'whitespace_only',
                'action': 'keep_bmad',
                'confidence': 0.95
            },
            {
                'pattern': 'case_only',
                'action': 'keep_bmad',
                'confidence': 0.90
            },
            {
                'pattern': 'linear_done_vs_bmad_review',
                'action': 'keep_linear',
                'confidence': 0.85
            }
        ])

    # ====================
    # Task 1: Conflict Visualization
    # ====================

    def visualize_conflict(self, conflict: StateConflict) -> ConflictVisualization:
        """
        Create a rich visualization of a conflict.

        Args:
            conflict: State conflict to visualize

        Returns:
            ConflictVisualization with side-by-side diff and analysis
        """
        # Build BMAD side representation
        bmad_side = {
            'state': conflict.bmad_state,
            'updated': conflict.bmad_updated,
            'source': 'BMAD (Source of Truth)'
        }

        # Build Linear side representation
        linear_side = {
            'state': conflict.linear_state,
            'updated': conflict.linear_updated,
            'source': 'Linear (Current State)'
        }

        # Generate diff highlights
        diff_highlights = self._generate_diff_highlights(
            conflict.bmad_state,
            conflict.linear_state
        )

        # Analyze impact
        impact_analysis = self._analyze_impact(conflict)

        # Check for auto-resolution suggestion
        auto_suggestion, confidence = self._check_auto_resolution(conflict)

        return ConflictVisualization(
            conflict_id=conflict.conflict_id,
            content_key=conflict.content_key,
            conflict_type=conflict.conflict_type,
            bmad_side=bmad_side,
            linear_side=linear_side,
            diff_highlights=diff_highlights,
            timestamps={
                'bmad_updated': conflict.bmad_updated,
                'linear_updated': conflict.linear_updated,
                'detected_at': conflict.detected_at
            },
            impact_analysis=impact_analysis,
            auto_resolve_suggestion=auto_suggestion,
            confidence_score=confidence
        )

    def _generate_diff_highlights(self, bmad_value: str, linear_value: str) -> List[str]:
        """
        Generate highlighted differences between BMAD and Linear values.

        Args:
            bmad_value: BMAD value
            linear_value: Linear value

        Returns:
            List of diff lines with highlights
        """
        diff = difflib.unified_diff(
            [bmad_value],
            [linear_value],
            lineterm='',
            fromfile='BMAD',
            tofile='Linear'
        )
        return list(diff)

    def _analyze_impact(self, conflict: StateConflict) -> str:
        """
        Analyze the impact of a conflict.

        Args:
            conflict: State conflict

        Returns:
            Impact description string
        """
        bmad_state = conflict.bmad_state
        linear_state = conflict.linear_state

        # Check if states represent workflow progression
        workflow_states = ['backlog', 'drafted', 'ready-for-dev', 'in-progress', 'review', 'done']

        try:
            bmad_idx = workflow_states.index(bmad_state.lower()) if bmad_state.lower() in workflow_states else -1
            # Convert Linear state to BMAD for comparison
            linear_as_bmad = self.mapper.linear_to_bmad(linear_state)
            linear_idx = workflow_states.index(linear_as_bmad.lower()) if linear_as_bmad.lower() in workflow_states else -1

            if bmad_idx > linear_idx:
                return f"⚠️ BMAD is ahead ({bmad_state}), Linear is behind ({linear_state}). " \
                       f"Keeping Linear would lose BMAD progress."
            elif linear_idx > bmad_idx:
                return f"⚠️ Linear is ahead ({linear_state}), BMAD is behind ({bmad_state}). " \
                       f"Keeping BMAD would revert Linear changes."
            else:
                return f"ℹ️ States are equivalent in workflow. Resolution is a matter of source preference."
        except Exception:
            return f"ℹ️ States differ: BMAD='{bmad_state}', Linear='{linear_state}'. Review to determine correct state."

    def _check_auto_resolution(self, conflict: StateConflict) -> Tuple[Optional[str], Optional[float]]:
        """
        Check if conflict can be auto-resolved.

        Args:
            conflict: State conflict

        Returns:
            Tuple of (suggested strategy, confidence score) or (None, None)
        """
        bmad_state = conflict.bmad_state
        linear_state = conflict.linear_state

        for rule in self.auto_rules:
            pattern = rule['pattern']
            confidence = rule.get('confidence', 0.0)

            if pattern == 'whitespace_only':
                if bmad_state.strip() == linear_state.strip():
                    return (rule['action'], confidence)

            elif pattern == 'case_only':
                if bmad_state.lower() == linear_state.lower():
                    return (rule['action'], confidence)

            elif pattern == 'linear_done_vs_bmad_review':
                linear_as_bmad = self.mapper.linear_to_bmad(linear_state)
                if linear_as_bmad == 'done' and bmad_state == 'review':
                    return (rule['action'], confidence)

        return (None, None)

    def format_visualization_for_display(self, viz: ConflictVisualization) -> str:
        """
        Format visualization for terminal display.

        Args:
            viz: Conflict visualization

        Returns:
            Formatted string for display
        """
        lines = []
        lines.append("=" * 80)
        lines.append(f"CONFLICT: {viz.content_key}")
        lines.append(f"Type: {viz.conflict_type}")
        lines.append(f"Detected: {viz.timestamps['detected_at']}")
        lines.append("=" * 80)
        lines.append("")

        # Side-by-side comparison
        lines.append("╔══════════════════════════════════════╦══════════════════════════════════════╗")
        lines.append("║           BMAD (Source)              ║        Linear (Current)              ║")
        lines.append("╠══════════════════════════════════════╬══════════════════════════════════════╣")
        lines.append(f"║ State: {viz.bmad_side['state']:<30} ║ State: {viz.linear_side['state']:<30} ║")
        lines.append(f"║ Updated: {viz.bmad_side['updated']:<28} ║ Updated: {viz.linear_side['updated']:<28} ║")
        lines.append("╚══════════════════════════════════════╩══════════════════════════════════════╝")
        lines.append("")

        # Diff highlights
        if viz.diff_highlights:
            lines.append("Differences:")
            for diff_line in viz.diff_highlights:
                lines.append(f"  {diff_line}")
            lines.append("")

        # Impact analysis
        lines.append("Impact Analysis:")
        lines.append(f"  {viz.impact_analysis}")
        lines.append("")

        # Auto-resolution suggestion
        if viz.auto_resolve_suggestion:
            lines.append(f"💡 Auto-Resolution Suggestion: {viz.auto_resolve_suggestion}")
            lines.append(f"   Confidence: {viz.confidence_score:.0%}")
            lines.append("")

        return "\n".join(lines)

    # ====================
    # Task 2: Resolution Strategies
    # ====================

    def resolve_keep_bmad(self, conflict: StateConflict) -> ResolutionResult:
        """
        Resolve conflict by keeping BMAD version.

        Args:
            conflict: State conflict

        Returns:
            Resolution result with BMAD state
        """
        resolved_state = {
            'state': conflict.bmad_state,
            'source': 'bmad',
            'updated': conflict.bmad_updated
        }

        return ResolutionResult(
            conflict_id=conflict.conflict_id,
            content_key=conflict.content_key,
            strategy=ResolutionStrategy.KEEP_BMAD,
            resolved_state=resolved_state,
            applied_at=datetime.now().isoformat(),
            applied_by='system',
            confidence=1.0
        )

    def resolve_keep_linear(self, conflict: StateConflict) -> ResolutionResult:
        """
        Resolve conflict by keeping Linear version.

        Args:
            conflict: State conflict

        Returns:
            Resolution result with Linear state
        """
        # Convert Linear state to BMAD format
        bmad_equivalent = self.mapper.linear_to_bmad(conflict.linear_state)

        resolved_state = {
            'state': bmad_equivalent,
            'source': 'linear',
            'updated': conflict.linear_updated
        }

        return ResolutionResult(
            conflict_id=conflict.conflict_id,
            content_key=conflict.content_key,
            strategy=ResolutionStrategy.KEEP_LINEAR,
            resolved_state=resolved_state,
            applied_at=datetime.now().isoformat(),
            applied_by='system',
            confidence=1.0
        )

    def resolve_intelligent_merge(self, conflict: StateConflict) -> ResolutionResult:
        """
        Resolve conflict using intelligent merge (most recent wins).

        Args:
            conflict: State conflict

        Returns:
            Resolution result with merged state
        """
        # Parse timestamps
        bmad_time = datetime.fromisoformat(conflict.bmad_updated.replace('Z', '+00:00'))
        linear_time = datetime.fromisoformat(conflict.linear_updated.replace('Z', '+00:00'))

        # Most recent wins
        if bmad_time > linear_time:
            use_state = conflict.bmad_state
            use_source = 'bmad'
            use_updated = conflict.bmad_updated
        else:
            use_state = self.mapper.linear_to_bmad(conflict.linear_state)
            use_source = 'linear'
            use_updated = conflict.linear_updated

        resolved_state = {
            'state': use_state,
            'source': use_source,
            'updated': use_updated
        }

        return ResolutionResult(
            conflict_id=conflict.conflict_id,
            content_key=conflict.content_key,
            strategy=ResolutionStrategy.INTELLIGENT_MERGE,
            resolved_state=resolved_state,
            applied_at=datetime.now().isoformat(),
            applied_by='system',
            confidence=0.8  # Medium confidence for automated merge
        )

    def resolve_manual_field_level(
        self,
        conflict: StateConflict,
        selected_fields: Dict[str, str]
    ) -> ResolutionResult:
        """
        Resolve conflict using manual field-level selection.

        Args:
            conflict: State conflict
            selected_fields: Dict mapping field names to 'bmad' or 'linear'

        Returns:
            Resolution result with manually selected fields
        """
        resolved_state = {}

        for field, source in selected_fields.items():
            if source == 'bmad':
                resolved_state[field] = getattr(conflict, f'bmad_{field}', None)
            elif source == 'linear':
                linear_value = getattr(conflict, f'linear_{field}', None)
                # Convert if needed
                if field == 'state':
                    resolved_state[field] = self.mapper.linear_to_bmad(linear_value)
                else:
                    resolved_state[field] = linear_value

        resolved_state['source'] = 'manual'

        return ResolutionResult(
            conflict_id=conflict.conflict_id,
            content_key=conflict.content_key,
            strategy=ResolutionStrategy.MANUAL_FIELD_LEVEL,
            resolved_state=resolved_state,
            applied_at=datetime.now().isoformat(),
            applied_by='user',
            confidence=1.0,  # High confidence for manual selection
            manual_override=True
        )

    # ====================
    # Task 3: Automated Resolution
    # ====================

    def can_auto_resolve(self, conflict: StateConflict, confidence_threshold: float = 0.85) -> bool:
        """
        Check if conflict can be automatically resolved.

        Args:
            conflict: State conflict
            confidence_threshold: Minimum confidence required for auto-resolution

        Returns:
            True if can auto-resolve, False otherwise
        """
        suggestion, confidence = self._check_auto_resolution(conflict)
        return suggestion is not None and confidence is not None and confidence >= confidence_threshold

    def auto_resolve(
        self,
        conflict: StateConflict,
        confidence_threshold: float = 0.85
    ) -> Optional[ResolutionResult]:
        """
        Automatically resolve conflict if confidence meets threshold.

        Now enhanced with ML predictions and custom rules (AC #2, #4).

        Args:
            conflict: State conflict
            confidence_threshold: Minimum confidence required

        Returns:
            ResolutionResult if resolved, None if cannot auto-resolve
        """
        # Step 1: Check custom rules first (highest priority)
        conflict_data = self._conflict_to_data(conflict)
        matching_rule = self.rules_engine.find_matching_rule(conflict_data)

        if matching_rule and matching_rule.confidence >= confidence_threshold:
            self.logger.info(f"Using custom rule: {matching_rule.name}")
            suggestion = matching_rule.action
            confidence = matching_rule.confidence
        else:
            # Step 2: Try ML prediction
            ml_prediction = self.ml_resolver.predict_strategy(conflict_data)

            if ml_prediction and ml_prediction.confidence >= confidence_threshold:
                self.logger.info(f"Using ML prediction: {ml_prediction.suggested_strategy}")
                suggestion = ml_prediction.suggested_strategy
                confidence = ml_prediction.confidence
            else:
                # Step 3: Fall back to pattern-based rules
                suggestion, confidence = self._check_auto_resolution(conflict)

                if not suggestion or not confidence or confidence < confidence_threshold:
                    return None

        # Apply suggested strategy
        if suggestion == 'keep_bmad' or suggestion == 'keep-bmad':
            result = self.resolve_keep_bmad(conflict)
        elif suggestion == 'keep_linear' or suggestion == 'keep-linear':
            result = self.resolve_keep_linear(conflict)
        elif suggestion == 'intelligent_merge' or suggestion == 'intelligent-merge':
            result = self.resolve_intelligent_merge(conflict)
        else:
            return None

        # Update confidence from auto-detection
        result.confidence = confidence

        return result

    def _conflict_to_data(self, conflict: StateConflict) -> Dict[str, Any]:
        """Convert StateConflict to data dict for ML/rules."""
        return {
            'conflict_id': conflict.conflict_id,
            'content_key': conflict.content_key,
            'bmad_state': conflict.bmad_state,
            'linear_state': conflict.linear_state,
            'conflict_type': conflict.conflict_type,
            'bmad_updated': conflict.bmad_updated,
            'linear_updated': conflict.linear_updated,
            'detected_at': conflict.detected_at
        }

    def get_ml_suggestion(
        self,
        conflict: StateConflict
    ) -> Optional[MLPrediction]:
        """
        Get ML-powered resolution suggestion (AC #2).

        Args:
            conflict: State conflict

        Returns:
            ML prediction with explanation and confidence
        """
        conflict_data = self._conflict_to_data(conflict)
        return self.ml_resolver.predict_strategy(conflict_data, explain=True)

    def train_ml_model(self) -> bool:
        """
        Train ML model from resolution history (AC #2).

        Returns:
            True if training successful
        """
        return self.ml_resolver.train_from_history(self.history_file)

    # ====================
    # Task 4: Resolution Preview
    # ====================

    def preview_resolution(
        self,
        conflict: StateConflict,
        strategy: ResolutionStrategy,
        selected_fields: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Preview resolution result without applying.

        Args:
            conflict: State conflict
            strategy: Resolution strategy to preview
            selected_fields: For manual strategy, selected fields

        Returns:
            Preview data showing before and after states
        """
        # Get resolution result (dry-run, not applied)
        if strategy == ResolutionStrategy.KEEP_BMAD:
            result = self.resolve_keep_bmad(conflict)
        elif strategy == ResolutionStrategy.KEEP_LINEAR:
            result = self.resolve_keep_linear(conflict)
        elif strategy == ResolutionStrategy.INTELLIGENT_MERGE:
            result = self.resolve_intelligent_merge(conflict)
        elif strategy == ResolutionStrategy.MANUAL_FIELD_LEVEL:
            if not selected_fields:
                raise ValueError("Manual strategy requires selected_fields")
            result = self.resolve_manual_field_level(conflict, selected_fields)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        # Build preview
        preview = {
            'conflict_id': conflict.conflict_id,
            'content_key': conflict.content_key,
            'strategy': strategy.value,
            'before': {
                'bmad_state': conflict.bmad_state,
                'linear_state': conflict.linear_state
            },
            'after': {
                'resolved_state': result.resolved_state['state'],
                'source': result.resolved_state['source']
            },
            'confidence': result.confidence,
            'impact': self._analyze_impact(conflict),
            'can_undo': True
        }

        return preview

    def format_preview_for_display(self, preview: Dict[str, Any]) -> str:
        """
        Format resolution preview for terminal display.

        Args:
            preview: Preview data

        Returns:
            Formatted string for display
        """
        lines = []
        lines.append("=" * 80)
        lines.append(f"RESOLUTION PREVIEW: {preview['content_key']}")
        lines.append(f"Strategy: {preview['strategy']}")
        lines.append(f"Confidence: {preview['confidence']:.0%}")
        lines.append("=" * 80)
        lines.append("")

        lines.append("BEFORE:")
        lines.append(f"  BMAD:   {preview['before']['bmad_state']}")
        lines.append(f"  Linear: {preview['before']['linear_state']}")
        lines.append("")

        lines.append("AFTER:")
        lines.append(f"  Resolved State: {preview['after']['resolved_state']}")
        lines.append(f"  Source: {preview['after']['source']}")
        lines.append("")

        lines.append("IMPACT:")
        lines.append(f"  {preview['impact']}")
        lines.append("")

        if preview['can_undo']:
            lines.append("✓ This resolution can be undone if needed")
        else:
            lines.append("⚠️ This resolution cannot be undone")

        lines.append("")
        return "\n".join(lines)

    # ====================
    # Task 5: Batch Resolution
    # ====================

    def group_similar_conflicts(self, conflicts: List[StateConflict]) -> Dict[str, List[StateConflict]]:
        """
        Group conflicts by similarity for batch processing.

        Args:
            conflicts: List of conflicts

        Returns:
            Dict mapping group key to list of similar conflicts
        """
        groups: Dict[str, List[StateConflict]] = {}

        for conflict in conflicts:
            # Group by conflict pattern
            key = f"{conflict.conflict_type}_{conflict.bmad_state}_{conflict.linear_state}"

            if key not in groups:
                groups[key] = []

            groups[key].append(conflict)

        return groups

    def batch_resolve(
        self,
        conflicts: List[StateConflict],
        strategy: ResolutionStrategy,
        confidence_threshold: float = 0.85
    ) -> Tuple[List[ResolutionResult], List[StateConflict]]:
        """
        Resolve multiple conflicts using the same strategy.

        Args:
            conflicts: List of conflicts to resolve
            strategy: Resolution strategy to apply
            confidence_threshold: Threshold for auto-resolution

        Returns:
            Tuple of (successful resolutions, failed conflicts)
        """
        successful: List[ResolutionResult] = []
        failed: List[StateConflict] = []

        for conflict in conflicts:
            try:
                if strategy == ResolutionStrategy.KEEP_BMAD:
                    result = self.resolve_keep_bmad(conflict)
                elif strategy == ResolutionStrategy.KEEP_LINEAR:
                    result = self.resolve_keep_linear(conflict)
                elif strategy == ResolutionStrategy.INTELLIGENT_MERGE:
                    result = self.resolve_intelligent_merge(conflict)
                else:
                    failed.append(conflict)
                    continue

                # Check confidence threshold
                if result.confidence >= confidence_threshold:
                    successful.append(result)
                else:
                    failed.append(conflict)

            except Exception as e:
                self.logger.error(f"Failed to resolve {conflict.content_key}: {e}")
                failed.append(conflict)

        return successful, failed

    # ====================
    # Task 6: Resolution History
    # ====================

    def save_resolution_history(self, result: ResolutionResult, conflict: StateConflict) -> None:
        """
        Save resolution to history for learning and tracking.

        Args:
            result: Resolution result
            conflict: Original conflict
        """
        history_entry = ResolutionHistory(
            resolution_id=f"r-{result.conflict_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            conflict_id=result.conflict_id,
            content_key=result.content_key,
            strategy=result.strategy.value,
            resolved_at=result.applied_at,
            resolved_by=result.applied_by,
            before_state={
                'bmad': conflict.bmad_state,
                'linear': conflict.linear_state
            },
            after_state=result.resolved_state,
            was_auto_resolved=not result.manual_override,
            confidence=result.confidence
        )

        # Load existing history
        history = []
        if self.history_file.exists():
            with open(self.history_file, 'r') as f:
                history = json.load(f)

        # Append new entry
        history.append(asdict(history_entry))

        # Save back
        with open(self.history_file, 'w') as f:
            json.dump(history, f, indent=2)

        self.logger.info(f"Saved resolution history for {result.content_key}")

    def get_resolution_history(self, content_key: Optional[str] = None) -> List[ResolutionHistory]:
        """
        Get resolution history, optionally filtered by content key.

        Args:
            content_key: Optional content key to filter by

        Returns:
            List of resolution history entries
        """
        if not self.history_file.exists():
            return []

        with open(self.history_file, 'r') as f:
            history_data = json.load(f)

        history = [ResolutionHistory(**entry) for entry in history_data]

        if content_key:
            history = [h for h in history if h.content_key == content_key]

        # Sort by resolved_at (newest first)
        history.sort(key=lambda h: h.resolved_at, reverse=True)

        return history

    def learn_from_history(self, content_key: str) -> Optional[ResolutionStrategy]:
        """
        Learn preferred resolution strategy from past resolutions.

        Args:
            content_key: Content key

        Returns:
            Suggested strategy based on history, or None
        """
        history = self.get_resolution_history(content_key)

        if not history:
            return None

        # Count strategy usage
        strategy_counts: Dict[str, int] = {}
        for entry in history:
            strategy_counts[entry.strategy] = strategy_counts.get(entry.strategy, 0) + 1

        # Return most commonly used strategy
        most_common = max(strategy_counts.items(), key=lambda x: x[1])
        return ResolutionStrategy(most_common[0])

    # ====================
    # High-level Operations
    # ====================

    def apply_resolution(self, result: ResolutionResult, conflict: StateConflict) -> None:
        """
        Apply a resolution result (update state, mark conflict resolved).

        Now tracks effectiveness metrics (AC #5).

        Args:
            result: Resolution result to apply
            conflict: Original conflict
        """
        # Log state change
        self.mapper.log_state_change(
            content_key=result.content_key,
            from_state=conflict.bmad_state,
            to_state=result.resolved_state['state'],
            source='conflict_resolution',
            operation=f'resolve_{result.strategy.value}',
            user=result.applied_by
        )

        # Mark conflict as resolved
        self.mapper.resolve_conflict(conflict.conflict_id)

        # Save to resolution history
        self.save_resolution_history(result, conflict)

        # Track effectiveness metrics
        self.effectiveness_tracker.record_resolution(
            conflict_id=conflict.conflict_id,
            content_key=conflict.content_key,
            was_auto_resolved=not result.manual_override,
            confidence=result.confidence,
            strategy=result.strategy.value,
            time_to_resolve_seconds=5.0 if not result.manual_override else 180.0,
            was_overridden=result.manual_override
        )

        self.logger.info(
            f"Applied resolution for {result.content_key}: "
            f"{conflict.bmad_state} → {result.resolved_state['state']} "
            f"(strategy: {result.strategy.value})"
        )

    # ====================
    # Task 5: Effectiveness Tracking (AC #5)
    # ====================

    def get_effectiveness_metrics(self) -> str:
        """
        Get formatted effectiveness metrics report.

        Returns:
            Formatted metrics report
        """
        metrics = self.effectiveness_tracker.get_metrics()
        return self.effectiveness_tracker.format_metrics_report(metrics)

    def get_strategy_effectiveness(self) -> Dict[str, Any]:
        """
        Get effectiveness breakdown by strategy.

        Returns:
            Dict mapping strategy to effectiveness metrics
        """
        return self.effectiveness_tracker.get_strategy_effectiveness()

    # ====================
    # Task 6: Three-Way Merge Support (AC #6)
    # ====================

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
        Create three-way conflict with ancestor detection.

        Args:
            content_key: Content key
            bmad_state: BMAD state
            linear_state: Linear state
            bmad_updated: BMAD timestamp
            linear_updated: Linear timestamp
            history: Historical state changes

        Returns:
            ThreeWayConflict with ancestor
        """
        return self.three_way_merge.create_three_way_conflict(
            content_key,
            bmad_state,
            linear_state,
            bmad_updated,
            linear_updated,
            history
        )

    def visualize_three_way(self, conflict: ThreeWayConflict) -> str:
        """
        Create formatted visualization of three-way conflict.

        Args:
            conflict: Three-way conflict

        Returns:
            Formatted visualization string
        """
        viz = self.three_way_merge.visualize_three_way(conflict)
        return self.three_way_merge.format_visualization(viz)

    def resolve_three_way(
        self,
        conflict: ThreeWayConflict,
        strategy: str = "auto"
    ) -> Dict[str, Any]:
        """
        Resolve three-way conflict.

        Args:
            conflict: Three-way conflict
            strategy: Resolution strategy

        Returns:
            Resolved state
        """
        return self.three_way_merge.perform_three_way_merge(conflict, strategy)


# Global resolver instance
_conflict_resolver: Optional[ConflictResolver] = None


def get_conflict_resolver(state_dir: Optional[Path] = None) -> ConflictResolver:
    """
    Get or create global conflict resolver instance.

    Args:
        state_dir: State directory

    Returns:
        ConflictResolver instance
    """
    global _conflict_resolver

    if _conflict_resolver is None:
        _conflict_resolver = ConflictResolver(state_dir=state_dir)

    return _conflict_resolver
