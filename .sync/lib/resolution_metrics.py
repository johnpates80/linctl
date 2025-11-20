#!/usr/bin/env python3
"""
Conflict Resolution Effectiveness Tracking.

Tracks metrics on resolution success rates, automation accuracy,
user overrides, and time savings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from logger import get_logger


@dataclass
class ResolutionMetrics:
    """Metrics for conflict resolution effectiveness."""
    total_resolutions: int
    auto_resolutions: int
    manual_resolutions: int
    auto_success_rate: float
    manual_override_count: int
    manual_override_rate: float
    avg_confidence: float
    total_time_saved_seconds: float
    period_start: str
    period_end: str


@dataclass
class MetricEntry:
    """Single metric entry."""
    timestamp: str
    conflict_id: str
    content_key: str
    was_auto_resolved: bool
    confidence: float
    strategy: str
    time_to_resolve_seconds: float
    was_overridden: bool
    user_satisfaction: Optional[int] = None  # 1-5 scale


class EffectivenessTracker:
    """Tracks conflict resolution effectiveness over time."""

    def __init__(self, metrics_dir: Optional[Path] = None):
        """
        Initialize effectiveness tracker.

        Args:
            metrics_dir: Directory for metrics (default: .sync/metrics/)
        """
        self.logger = get_logger()
        self.metrics_dir = metrics_dir or Path('.sync/metrics')
        self.metrics_dir.mkdir(parents=True, exist_ok=True)

        self.metrics_file = self.metrics_dir / 'resolution_effectiveness.json'
        self._initialize_metrics()

    def _initialize_metrics(self) -> None:
        """Initialize metrics file if it doesn't exist."""
        if not self.metrics_file.exists():
            initial_data = {
                'entries': [],
                'summary': {
                    'total_resolutions': 0,
                    'auto_resolutions': 0,
                    'manual_resolutions': 0,
                    'total_time_saved_seconds': 0.0
                }
            }
            with open(self.metrics_file, 'w') as f:
                json.dump(initial_data, f, indent=2)

    def record_resolution(
        self,
        conflict_id: str,
        content_key: str,
        was_auto_resolved: bool,
        confidence: float,
        strategy: str,
        time_to_resolve_seconds: float,
        was_overridden: bool = False
    ) -> None:
        """
        Record a resolution event.

        Args:
            conflict_id: Conflict ID
            content_key: Content key
            was_auto_resolved: Whether auto-resolved
            confidence: Confidence score
            strategy: Resolution strategy used
            time_to_resolve_seconds: Time taken
            was_overridden: Whether user overrode suggestion
        """
        entry = MetricEntry(
            timestamp=datetime.now().isoformat(),
            conflict_id=conflict_id,
            content_key=content_key,
            was_auto_resolved=was_auto_resolved,
            confidence=confidence,
            strategy=strategy,
            time_to_resolve_seconds=time_to_resolve_seconds,
            was_overridden=was_overridden
        )

        # Load existing data
        with open(self.metrics_file, 'r') as f:
            data = json.load(f)

        # Add new entry
        data['entries'].append(asdict(entry))

        # Update summary
        data['summary']['total_resolutions'] += 1
        if was_auto_resolved:
            data['summary']['auto_resolutions'] += 1
            # Estimate time saved (manual resolution typically takes 2-5 minutes)
            data['summary']['total_time_saved_seconds'] += 180  # 3 minutes avg
        else:
            data['summary']['manual_resolutions'] += 1

        # Save back
        with open(self.metrics_file, 'w') as f:
            json.dump(data, f, indent=2)

        self.logger.info(f"Recorded resolution metric for {content_key}")

    def get_metrics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> ResolutionMetrics:
        """
        Calculate metrics for a time period.

        Args:
            start_date: Start of period (default: 30 days ago)
            end_date: End of period (default: now)

        Returns:
            ResolutionMetrics summary
        """
        if not self.metrics_file.exists():
            return ResolutionMetrics(
                total_resolutions=0,
                auto_resolutions=0,
                manual_resolutions=0,
                auto_success_rate=0.0,
                manual_override_count=0,
                manual_override_rate=0.0,
                avg_confidence=0.0,
                total_time_saved_seconds=0.0,
                period_start='',
                period_end=''
            )

        # Set default time range
        if not end_date:
            end_date = datetime.now()
        if not start_date:
            start_date = end_date - timedelta(days=30)

        # Load data
        with open(self.metrics_file, 'r') as f:
            data = json.load(f)

        # Filter entries by date range
        entries = []
        for entry_data in data['entries']:
            entry_time = datetime.fromisoformat(entry_data['timestamp'])
            if start_date <= entry_time <= end_date:
                entries.append(MetricEntry(**entry_data))

        # Calculate metrics
        total = len(entries)
        auto = sum(1 for e in entries if e.was_auto_resolved)
        manual = total - auto
        overrides = sum(1 for e in entries if e.was_overridden)

        avg_confidence = sum(e.confidence for e in entries) / total if total > 0 else 0.0

        # Auto success rate: auto-resolutions that were NOT overridden
        auto_success = sum(1 for e in entries if e.was_auto_resolved and not e.was_overridden)
        auto_success_rate = auto_success / auto if auto > 0 else 0.0

        override_rate = overrides / total if total > 0 else 0.0

        time_saved = auto * 180  # 3 minutes per auto-resolution

        return ResolutionMetrics(
            total_resolutions=total,
            auto_resolutions=auto,
            manual_resolutions=manual,
            auto_success_rate=auto_success_rate,
            manual_override_count=overrides,
            manual_override_rate=override_rate,
            avg_confidence=avg_confidence,
            total_time_saved_seconds=time_saved,
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat()
        )

    def get_strategy_effectiveness(
        self,
        start_date: Optional[datetime] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get effectiveness breakdown by strategy.

        Args:
            start_date: Start date for analysis

        Returns:
            Dict mapping strategy to effectiveness metrics
        """
        if not start_date:
            start_date = datetime.now() - timedelta(days=30)

        with open(self.metrics_file, 'r') as f:
            data = json.load(f)

        # Filter entries
        entries = []
        for entry_data in data['entries']:
            entry_time = datetime.fromisoformat(entry_data['timestamp'])
            if entry_time >= start_date:
                entries.append(MetricEntry(**entry_data))

        # Group by strategy
        strategy_metrics: Dict[str, List[MetricEntry]] = {}
        for entry in entries:
            if entry.strategy not in strategy_metrics:
                strategy_metrics[entry.strategy] = []
            strategy_metrics[entry.strategy].append(entry)

        # Calculate effectiveness for each strategy
        effectiveness = {}
        for strategy, strategy_entries in strategy_metrics.items():
            total = len(strategy_entries)
            auto = sum(1 for e in strategy_entries if e.was_auto_resolved)
            overrides = sum(1 for e in strategy_entries if e.was_overridden)
            avg_conf = sum(e.confidence for e in strategy_entries) / total

            effectiveness[strategy] = {
                'total_uses': total,
                'auto_uses': auto,
                'override_count': overrides,
                'override_rate': overrides / total if total > 0 else 0.0,
                'avg_confidence': avg_conf,
                'success_rate': (total - overrides) / total if total > 0 else 0.0
            }

        return effectiveness

    def record_user_satisfaction(
        self,
        conflict_id: str,
        satisfaction: int
    ) -> None:
        """
        Record user satisfaction score for a resolution.

        Args:
            conflict_id: Conflict ID
            satisfaction: Score 1-5 (1=poor, 5=excellent)
        """
        if not 1 <= satisfaction <= 5:
            raise ValueError("Satisfaction must be 1-5")

        with open(self.metrics_file, 'r') as f:
            data = json.load(f)

        # Find entry and update
        for entry in data['entries']:
            if entry['conflict_id'] == conflict_id:
                entry['user_satisfaction'] = satisfaction
                break

        with open(self.metrics_file, 'w') as f:
            json.dump(data, f, indent=2)

        self.logger.info(f"Recorded satisfaction score {satisfaction} for {conflict_id}")

    # Alias for convenience
    def record_satisfaction(self, conflict_id: str, satisfaction: int) -> None:
        """Alias for record_user_satisfaction."""
        return self.record_user_satisfaction(conflict_id, satisfaction)

    def get_satisfaction_summary(self) -> Dict[str, Any]:
        """Get summary of user satisfaction scores."""
        with open(self.metrics_file, 'r') as f:
            data = json.load(f)

        scores = [
            e['user_satisfaction']
            for e in data['entries']
            if e.get('user_satisfaction') is not None
        ]

        if not scores:
            return {
                'total_ratings': 0,
                'avg_satisfaction': 0.0,
                'distribution': {}
            }

        return {
            'total_ratings': len(scores),
            'avg_satisfaction': sum(scores) / len(scores),
            'distribution': {
                i: scores.count(i)
                for i in range(1, 6)
            }
        }

    def format_metrics_report(self, metrics: ResolutionMetrics) -> str:
        """
        Format metrics as a readable report.

        Args:
            metrics: Resolution metrics

        Returns:
            Formatted report string
        """
        lines = []
        lines.append("=" * 80)
        lines.append("CONFLICT RESOLUTION EFFECTIVENESS REPORT")
        lines.append("=" * 80)
        lines.append(f"Period: {metrics.period_start} to {metrics.period_end}")
        lines.append("")

        lines.append("RESOLUTION COUNTS:")
        lines.append(f"  Total Resolutions: {metrics.total_resolutions}")
        lines.append(f"  Auto Resolutions: {metrics.auto_resolutions}")
        lines.append(f"  Manual Resolutions: {metrics.manual_resolutions}")
        lines.append("")

        lines.append("EFFECTIVENESS METRICS:")
        lines.append(f"  Auto Success Rate: {metrics.auto_success_rate:.1%}")
        lines.append(f"  Manual Override Count: {metrics.manual_override_count}")
        lines.append(f"  Manual Override Rate: {metrics.manual_override_rate:.1%}")
        lines.append(f"  Average Confidence: {metrics.avg_confidence:.1%}")
        lines.append("")

        lines.append("TIME SAVINGS:")
        time_saved_minutes = metrics.total_time_saved_seconds / 60
        time_saved_hours = time_saved_minutes / 60
        lines.append(f"  Total Time Saved: {time_saved_hours:.1f} hours ({time_saved_minutes:.0f} minutes)")
        lines.append("")

        return "\n".join(lines)


# Global tracker instance
_effectiveness_tracker: Optional[EffectivenessTracker] = None


def get_effectiveness_tracker(metrics_dir: Optional[Path] = None) -> EffectivenessTracker:
    """
    Get or create global effectiveness tracker instance.

    Args:
        metrics_dir: Metrics directory

    Returns:
        EffectivenessTracker instance
    """
    global _effectiveness_tracker

    if _effectiveness_tracker is None:
        _effectiveness_tracker = EffectivenessTracker(metrics_dir=metrics_dir)

    return _effectiveness_tracker
