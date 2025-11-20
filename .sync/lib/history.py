#!/usr/bin/env python3
"""
Historical tracking and trend analysis for BMAD sync system.

Maintains sync history with metrics, trends, and retention policies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import hashlib


@dataclass
class SyncHistoryEntry:
    """Single sync history entry."""
    timestamp: str
    operation: str
    result: str
    duration_ms: Optional[int]
    stories_processed: int
    api_calls: int
    errors: List[str]
    metadata: Dict[str, Any]


class HistoryTracker:
    """Manages sync history and trend analysis."""

    def __init__(self, history_dir: Optional[Path] = None):
        """
        Initialize history tracker.

        Args:
            history_dir: Directory for history files (default: .sync/history/)
        """
        if history_dir is None:
            current_dir = Path.cwd()
            while current_dir != current_dir.parent:
                if (current_dir / '.sync').exists():
                    history_dir = current_dir / '.sync' / 'history'
                    break
                current_dir = current_dir.parent

            if history_dir is None:
                history_dir = Path('.sync/history')

        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)

        # Retention policy: 90 days
        self.retention_days = 90

    def record_sync(
        self,
        operation: str,
        result: str,
        duration_ms: Optional[int] = None,
        stories_processed: int = 0,
        api_calls: int = 0,
        errors: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record a sync operation to history.

        Args:
            operation: Operation name
            result: Result status ('success', 'failure', 'partial')
            duration_ms: Duration in milliseconds
            stories_processed: Number of stories processed
            api_calls: Number of API calls made
            errors: List of error messages
            metadata: Additional metadata
        """
        entry = SyncHistoryEntry(
            timestamp=datetime.now().isoformat(),
            operation=operation,
            result=result,
            duration_ms=duration_ms,
            stories_processed=stories_processed,
            api_calls=api_calls,
            errors=errors or [],
            metadata=metadata or {}
        )

        # Write to daily file
        self._append_to_daily_file(entry)

        # Cleanup old files
        self._cleanup_old_history()

    def get_history(
        self,
        days: Optional[int] = None,
        operation: Optional[str] = None,
        result: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get history entries with optional filters.

        Args:
            days: Number of days to retrieve (None = all available)
            operation: Filter by operation name
            result: Filter by result status

        Returns:
            List of history entries
        """
        entries = []

        # Determine date range
        if days is not None:
            cutoff = datetime.now() - timedelta(days=days)
        else:
            cutoff = None

        # Read all history files
        for history_file in sorted(self.history_dir.glob('*.jsonl')):
            try:
                with open(history_file, 'r') as f:
                    for line in f:
                        if line.strip():
                            entry = json.loads(line)

                            # Apply filters
                            if cutoff:
                                entry_time = datetime.fromisoformat(entry['timestamp'])
                                if entry_time < cutoff:
                                    continue

                            if operation and entry.get('operation') != operation:
                                continue

                            if result and entry.get('result') != result:
                                continue

                            entries.append(entry)
            except Exception:
                continue

        return entries

    def get_trend_analysis(self, days: int = 30) -> Dict[str, Any]:
        """
        Analyze trends over time period.

        Args:
            days: Number of days to analyze

        Returns:
            Dictionary with trend analysis
        """
        history = self.get_history(days=days)

        if not history:
            return {
                'period_days': days,
                'total_syncs': 0,
                'success_rate': 0.0,
                'avg_duration_ms': None,
                'avg_stories_per_sync': 0.0,
                'total_api_calls': 0,
                'total_errors': 0,
                'trends': {}
            }

        # Calculate metrics
        total_syncs = len(history)
        successful = sum(1 for e in history if e.get('result') == 'success')
        success_rate = (successful / total_syncs * 100) if total_syncs > 0 else 0.0

        # Average duration
        durations = [e.get('duration_ms') for e in history if e.get('duration_ms') is not None]
        avg_duration_ms = sum(durations) / len(durations) if durations else None

        # Average stories per sync
        stories_counts = [e.get('stories_processed', 0) for e in history]
        avg_stories = sum(stories_counts) / len(stories_counts) if stories_counts else 0.0

        # Total API calls
        total_api_calls = sum(e.get('api_calls', 0) for e in history)

        # Total errors
        total_errors = sum(len(e.get('errors', [])) for e in history)

        # Daily trends
        daily_trends = self._calculate_daily_trends(history)

        return {
            'period_days': days,
            'total_syncs': total_syncs,
            'success_rate': round(success_rate, 2),
            'avg_duration_ms': round(avg_duration_ms, 2) if avg_duration_ms else None,
            'avg_stories_per_sync': round(avg_stories, 2),
            'total_api_calls': total_api_calls,
            'total_errors': total_errors,
            'trends': daily_trends
        }

    def render_trends(self, days: int = 30) -> str:
        """
        Render trend analysis as formatted text.

        Args:
            days: Number of days to analyze

        Returns:
            Formatted trend report
        """
        analysis = self.get_trend_analysis(days=days)

        lines = []
        lines.append("=" * 60)
        lines.append(f"  Sync Trends - Last {days} Days")
        lines.append("=" * 60)
        lines.append("")

        lines.append(f"Total Syncs: {analysis['total_syncs']}")
        lines.append(f"Success Rate: {analysis['success_rate']}%")
        lines.append("")

        if analysis['avg_duration_ms']:
            avg_sec = analysis['avg_duration_ms'] / 1000
            lines.append(f"Average Duration: {avg_sec:.2f}s")

        lines.append(f"Average Stories/Sync: {analysis['avg_stories_per_sync']}")
        lines.append(f"Total API Calls: {analysis['total_api_calls']}")
        lines.append(f"Total Errors: {analysis['total_errors']}")
        lines.append("")

        # Daily trends chart (simple ASCII)
        trends = analysis['trends']
        if trends:
            lines.append("Daily Sync Frequency:")
            max_count = max(trends.values()) if trends.values() else 1

            for date, count in sorted(trends.items())[-14:]:  # Last 14 days
                bar_length = int((count / max_count) * 40)
                bar = '█' * bar_length
                lines.append(f"  {date}: {bar} {count}")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)

    def _append_to_daily_file(self, entry: SyncHistoryEntry) -> None:
        """Append entry to daily history file."""
        date = datetime.now().strftime('%Y-%m-%d')
        filename = f"sync_history_{date}.jsonl"
        filepath = self.history_dir / filename

        with open(filepath, 'a') as f:
            f.write(json.dumps(asdict(entry)) + '\n')

    def _cleanup_old_history(self) -> None:
        """Remove history files older than retention period."""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        cutoff_date_str = cutoff.strftime('%Y-%m-%d')

        for history_file in self.history_dir.glob('sync_history_*.jsonl'):
            try:
                # Extract date from filename
                date_str = history_file.stem.replace('sync_history_', '')
                if date_str < cutoff_date_str:
                    history_file.unlink()
            except Exception:
                continue

    def _calculate_daily_trends(self, history: List[Dict[str, Any]]) -> Dict[str, int]:
        """Calculate daily sync counts."""
        daily_counts: Dict[str, int] = {}

        for entry in history:
            try:
                timestamp = datetime.fromisoformat(entry['timestamp'])
                date_key = timestamp.strftime('%Y-%m-%d')
                daily_counts[date_key] = daily_counts.get(date_key, 0) + 1
            except (ValueError, TypeError, KeyError):
                continue

        return daily_counts

    def export_history(
        self,
        output_path: Path,
        days: Optional[int] = None,
        format: str = 'json'
    ) -> None:
        """
        Export history to file.

        Args:
            output_path: Output file path
            days: Number of days to export (None = all)
            format: Export format ('json', 'csv')
        """
        history = self.get_history(days=days)

        if format == 'json':
            output_path.write_text(json.dumps(history, indent=2), encoding='utf-8')
        elif format == 'csv':
            import csv
            with open(output_path, 'w', newline='') as f:
                if history:
                    fieldnames = ['timestamp', 'operation', 'result', 'duration_ms',
                                'stories_processed', 'api_calls', 'errors']
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(history)


def record_sync(
    operation: str,
    result: str,
    **kwargs
) -> None:
    """
    Record sync operation (convenience function).

    Args:
        operation: Operation name
        result: Result status
        **kwargs: Additional parameters for record_sync
    """
    tracker = HistoryTracker()
    tracker.record_sync(operation, result, **kwargs)


if __name__ == '__main__':
    # Demo history tracking
    tracker = HistoryTracker()

    # Record some sample syncs
    tracker.record_sync(
        operation='sync_all',
        result='success',
        duration_ms=1500,
        stories_processed=12,
        api_calls=25
    )

    # Show trends
    print(tracker.render_trends(days=30))
