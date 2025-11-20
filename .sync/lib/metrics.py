#!/usr/bin/env python3
"""
Performance metrics collection and analysis for BMAD sync system.

Tracks sync duration, throughput, API calls, and identifies bottlenecks.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from contextlib import contextmanager
from dataclasses import dataclass, asdict


@dataclass
class PerformanceMetrics:
    """Performance metrics for a sync operation."""
    operation: str
    started_at: str
    completed_at: Optional[str]
    duration_ms: Optional[int]
    stories_processed: int
    api_calls: int
    api_call_duration_ms: int
    throughput_stories_per_sec: Optional[float]
    bottlenecks: List[Dict[str, Any]]


class MetricsCollector:
    """Collects and analyzes performance metrics."""

    def __init__(self, metrics_dir: Optional[Path] = None):
        """
        Initialize metrics collector.

        Args:
            metrics_dir: Directory for metrics files (default: .sync/metrics/)
        """
        if metrics_dir is None:
            current_dir = Path.cwd()
            while current_dir != current_dir.parent:
                if (current_dir / '.sync').exists():
                    metrics_dir = current_dir / '.sync' / 'metrics'
                    break
                current_dir = current_dir.parent

            if metrics_dir is None:
                metrics_dir = Path('.sync/metrics')

        self.metrics_dir = Path(metrics_dir)
        self.metrics_dir.mkdir(parents=True, exist_ok=True)

        # Current operation metrics
        self.current_metrics: Optional[Dict[str, Any]] = None
        self.operation_timings: List[Dict[str, Any]] = []

    @contextmanager
    def track_operation(self, operation: str):
        """
        Context manager to track operation performance.

        Args:
            operation: Operation name

        Yields:
            Metrics dictionary for recording

        Example:
            with metrics.track_operation('sync_stories'):
                # ... perform sync ...
                pass
        """
        metrics = {
            'operation': operation,
            'started_at': datetime.now().isoformat(),
            'start_time_ms': time.time() * 1000,
            'stories_processed': 0,
            'api_calls': 0,
            'api_call_duration_ms': 0,
            'timings': []
        }

        self.current_metrics = metrics

        try:
            yield metrics
        finally:
            # Calculate final metrics
            end_time_ms = time.time() * 1000
            metrics['completed_at'] = datetime.now().isoformat()
            metrics['duration_ms'] = int(end_time_ms - metrics['start_time_ms'])

            # Calculate throughput
            if metrics['duration_ms'] > 0 and metrics['stories_processed'] > 0:
                duration_sec = metrics['duration_ms'] / 1000
                metrics['throughput_stories_per_sec'] = metrics['stories_processed'] / duration_sec
            else:
                metrics['throughput_stories_per_sec'] = None

            # Identify bottlenecks
            metrics['bottlenecks'] = self._identify_bottlenecks(metrics)

            # Save metrics
            self._save_metrics(metrics)

            self.current_metrics = None

    def record_api_call(self, duration_ms: int) -> None:
        """
        Record an API call and its duration.

        Args:
            duration_ms: API call duration in milliseconds
        """
        if self.current_metrics:
            self.current_metrics['api_calls'] += 1
            self.current_metrics['api_call_duration_ms'] += duration_ms

    def record_story_processed(self) -> None:
        """Record that a story was processed."""
        if self.current_metrics:
            self.current_metrics['stories_processed'] += 1

    @contextmanager
    def time_operation(self, operation_name: str):
        """
        Context manager to time a specific operation.

        Args:
            operation_name: Name of the operation

        Yields:
            None

        Example:
            with metrics.time_operation('parse_story'):
                # ... parsing code ...
                pass
        """
        start_ms = time.time() * 1000

        try:
            yield
        finally:
            end_ms = time.time() * 1000
            duration_ms = int(end_ms - start_ms)

            if self.current_metrics:
                self.current_metrics['timings'].append({
                    'operation': operation_name,
                    'duration_ms': duration_ms
                })

    def get_performance_report(self, days: int = 7) -> Dict[str, Any]:
        """
        Get performance report for time period.

        Args:
            days: Number of days to analyze

        Returns:
            Dictionary with performance analysis
        """
        metrics = self._load_recent_metrics(days=days)

        if not metrics:
            return {
                'period_days': days,
                'total_operations': 0,
                'avg_duration_ms': None,
                'avg_throughput': None,
                'total_api_calls': 0,
                'avg_api_calls_per_sync': 0,
                'common_bottlenecks': []
            }

        # Calculate aggregated metrics
        total_ops = len(metrics)
        durations = [m['duration_ms'] for m in metrics if m.get('duration_ms')]
        avg_duration = sum(durations) / len(durations) if durations else None

        throughputs = [m['throughput_stories_per_sec'] for m in metrics
                      if m.get('throughput_stories_per_sec')]
        avg_throughput = sum(throughputs) / len(throughputs) if throughputs else None

        total_api_calls = sum(m.get('api_calls', 0) for m in metrics)
        avg_api_calls = total_api_calls / total_ops if total_ops > 0 else 0

        # Analyze bottlenecks
        bottleneck_counts: Dict[str, int] = {}
        for m in metrics:
            for bottleneck in m.get('bottlenecks', []):
                bn_type = bottleneck.get('type', 'unknown')
                bottleneck_counts[bn_type] = bottleneck_counts.get(bn_type, 0) + 1

        common_bottlenecks = [
            {'type': bn_type, 'occurrences': count}
            for bn_type, count in sorted(bottleneck_counts.items(),
                                        key=lambda x: x[1], reverse=True)
        ][:5]

        return {
            'period_days': days,
            'total_operations': total_ops,
            'avg_duration_ms': round(avg_duration, 2) if avg_duration else None,
            'avg_throughput': round(avg_throughput, 2) if avg_throughput else None,
            'total_api_calls': total_api_calls,
            'avg_api_calls_per_sync': round(avg_api_calls, 2),
            'common_bottlenecks': common_bottlenecks
        }

    def render_performance_report(self, days: int = 7) -> str:
        """
        Render performance report as formatted text.

        Args:
            days: Number of days to analyze

        Returns:
            Formatted performance report
        """
        report = self.get_performance_report(days=days)

        lines = []
        lines.append("=" * 60)
        lines.append(f"  Performance Report - Last {days} Days")
        lines.append("=" * 60)
        lines.append("")

        lines.append(f"Total Operations: {report['total_operations']}")
        lines.append("")

        if report['avg_duration_ms']:
            avg_sec = report['avg_duration_ms'] / 1000
            lines.append(f"Average Duration: {avg_sec:.2f}s")

        if report['avg_throughput']:
            lines.append(f"Average Throughput: {report['avg_throughput']:.2f} stories/sec")

        lines.append(f"Total API Calls: {report['total_api_calls']}")
        lines.append(f"Average API Calls/Sync: {report['avg_api_calls_per_sync']:.1f}")
        lines.append("")

        # Bottlenecks
        if report['common_bottlenecks']:
            lines.append("Common Bottlenecks:")
            for bn in report['common_bottlenecks']:
                lines.append(f"  • {bn['type']}: {bn['occurrences']} occurrences")
            lines.append("")

        lines.append("=" * 60)

        return "\n".join(lines)

    def _identify_bottlenecks(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Identify performance bottlenecks."""
        bottlenecks = []

        duration_ms = metrics.get('duration_ms', 0)
        api_duration = metrics.get('api_call_duration_ms', 0)

        # API calls taking >50% of time
        if duration_ms > 0 and api_duration > duration_ms * 0.5:
            bottlenecks.append({
                'type': 'api_overhead',
                'severity': 'high',
                'description': f"API calls taking {api_duration}ms ({api_duration/duration_ms*100:.1f}% of total)",
                'recommendation': 'Consider batching API calls or caching'
            })

        # Low throughput
        throughput = metrics.get('throughput_stories_per_sec', 0)
        if throughput and throughput < 1.0:
            bottlenecks.append({
                'type': 'low_throughput',
                'severity': 'medium',
                'description': f"Low throughput: {throughput:.2f} stories/sec",
                'recommendation': 'Review story processing logic for optimization'
            })

        # Analyze operation timings
        timings = metrics.get('timings', [])
        if timings:
            sorted_timings = sorted(timings, key=lambda x: x['duration_ms'], reverse=True)
            slowest = sorted_timings[0]

            if slowest['duration_ms'] > duration_ms * 0.3:
                bottlenecks.append({
                    'type': 'slow_operation',
                    'severity': 'medium',
                    'description': f"{slowest['operation']} taking {slowest['duration_ms']}ms",
                    'recommendation': f"Optimize {slowest['operation']} operation"
                })

        return bottlenecks

    def _save_metrics(self, metrics: Dict[str, Any]) -> None:
        """Save metrics to file."""
        date = datetime.now().strftime('%Y-%m-%d')
        filename = f"metrics_{date}.jsonl"
        filepath = self.metrics_dir / filename

        # Remove timing info (can be large)
        metrics_to_save = metrics.copy()
        metrics_to_save.pop('start_time_ms', None)
        metrics_to_save.pop('timings', None)

        with open(filepath, 'a') as f:
            f.write(json.dumps(metrics_to_save) + '\n')

    def _load_recent_metrics(self, days: int) -> List[Dict[str, Any]]:
        """Load metrics from recent days."""
        metrics = []

        for metrics_file in sorted(self.metrics_dir.glob('metrics_*.jsonl')):
            try:
                with open(metrics_file, 'r') as f:
                    for line in f:
                        if line.strip():
                            entry = json.loads(line)
                            metrics.append(entry)
            except Exception:
                continue

        return metrics


# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector(metrics_dir: Optional[Path] = None) -> MetricsCollector:
    """
    Get or create global metrics collector instance.

    Args:
        metrics_dir: Directory for metrics files

    Returns:
        MetricsCollector instance
    """
    global _metrics_collector

    if _metrics_collector is None:
        _metrics_collector = MetricsCollector(metrics_dir=metrics_dir)

    return _metrics_collector


if __name__ == '__main__':
    # Demo metrics collection
    metrics = MetricsCollector()

    with metrics.track_operation('demo_sync') as m:
        time.sleep(0.1)
        metrics.record_api_call(50)
        metrics.record_story_processed()

        with metrics.time_operation('parse_stories'):
            time.sleep(0.05)

    print(metrics.render_performance_report(days=7))
