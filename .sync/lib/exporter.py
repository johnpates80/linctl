#!/usr/bin/env python3
"""
Report export utilities for BMAD sync system.

Supports export to JSON, Markdown, and CSV formats.
"""

from __future__ import annotations

import json
import csv
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from dashboard import Dashboard
from history import HistoryTracker
from metrics import MetricsCollector


class ReportExporter:
    """Exports sync reports in multiple formats."""

    def __init__(self):
        """Initialize report exporter."""
        self.dashboard = Dashboard()
        self.history = HistoryTracker()
        self.metrics = MetricsCollector()

    def export_dashboard(self, output_path: Path, format: str = 'json') -> None:
        """
        Export dashboard data.

        Args:
            output_path: Output file path
            format: Export format ('json', 'markdown')
        """
        if format == 'json':
            data = self.dashboard.get_dashboard_data()
            output_path.write_text(json.dumps(data, indent=2), encoding='utf-8')

        elif format == 'markdown':
            content = self._render_dashboard_markdown()
            output_path.write_text(content, encoding='utf-8')

    def export_history(
        self,
        output_path: Path,
        format: str = 'json',
        days: Optional[int] = None
    ) -> None:
        """
        Export sync history.

        Args:
            output_path: Output file path
            format: Export format ('json', 'csv', 'markdown')
            days: Number of days to export (None = all)
        """
        history = self.history.get_history(days=days)

        if format == 'json':
            output_path.write_text(json.dumps(history, indent=2), encoding='utf-8')

        elif format == 'csv':
            self._export_history_csv(history, output_path)

        elif format == 'markdown':
            content = self._render_history_markdown(history, days)
            output_path.write_text(content, encoding='utf-8')

    def export_metrics(
        self,
        output_path: Path,
        format: str = 'json',
        days: int = 7
    ) -> None:
        """
        Export performance metrics.

        Args:
            output_path: Output file path
            format: Export format ('json', 'markdown')
            days: Number of days to analyze
        """
        report = self.metrics.get_performance_report(days=days)

        if format == 'json':
            output_path.write_text(json.dumps(report, indent=2), encoding='utf-8')

        elif format == 'markdown':
            content = self._render_metrics_markdown(report)
            output_path.write_text(content, encoding='utf-8')

    def export_full_report(
        self,
        output_path: Path,
        format: str = 'markdown',
        days: int = 7
    ) -> None:
        """
        Export comprehensive report with all data.

        Args:
            output_path: Output file path
            format: Export format ('json', 'markdown')
            days: Number of days for historical data
        """
        if format == 'json':
            data = {
                'generated_at': datetime.now().isoformat(),
                'dashboard': self.dashboard.get_dashboard_data(),
                'history': self.history.get_history(days=days),
                'trends': self.history.get_trend_analysis(days=days),
                'metrics': self.metrics.get_performance_report(days=days)
            }
            output_path.write_text(json.dumps(data, indent=2), encoding='utf-8')

        elif format == 'markdown':
            content = self._render_full_report_markdown(days)
            output_path.write_text(content, encoding='utf-8')

    def _render_dashboard_markdown(self) -> str:
        """Render dashboard as Markdown."""
        status = self.dashboard.get_project_status()

        lines = []
        lines.append(f"# BMAD Sync Dashboard - {status.project_name}")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # Health section
        health_emoji = {'OK': '✅', 'DEGRADED': '⚠️', 'POOR': '❌'}.get(status.health_status, '❓')
        lines.append(f"## Health Status: {health_emoji} {status.health_status}")
        lines.append("")
        lines.append(f"**Score:** {status.health_score}/100")
        lines.append("")

        # Sync info
        lines.append("## Last Sync")
        lines.append("")
        if status.last_sync:
            lines.append(f"- **Time:** {status.last_sync}")
            if status.sync_duration_ms:
                duration_sec = status.sync_duration_ms / 1000
                lines.append(f"- **Duration:** {duration_sec:.2f}s")
        else:
            lines.append("- **Time:** Never")
        lines.append("")

        # Metrics
        lines.append("## Metrics")
        lines.append("")
        lines.append(f"- **Stories Tracked:** {status.stories_synced}")
        lines.append(f"- **Linear Issues:** {status.linear_issue_count}")
        lines.append(f"- **Active Conflicts:** {status.active_conflicts}")
        lines.append(f"- **Recent Errors (24h):** {status.recent_errors}")
        lines.append("")

        return "\n".join(lines)

    def _render_history_markdown(
        self,
        history: List[Dict[str, Any]],
        days: Optional[int]
    ) -> str:
        """Render history as Markdown."""
        lines = []
        lines.append("# Sync History")
        lines.append("")

        if days:
            lines.append(f"**Period:** Last {days} days")
        else:
            lines.append("**Period:** All available history")

        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Total Operations:** {len(history)}")
        lines.append("")

        # Table
        lines.append("## Operations")
        lines.append("")
        lines.append("| Timestamp | Operation | Result | Duration | Stories | API Calls | Errors |")
        lines.append("|-----------|-----------|--------|----------|---------|-----------|--------|")

        for entry in history[-50:]:  # Last 50 entries
            timestamp = entry.get('timestamp', '')[:19]
            operation = entry.get('operation', '')
            result = entry.get('result', '')
            duration_ms = entry.get('duration_ms')
            duration = f"{duration_ms}ms" if duration_ms else "N/A"
            stories = entry.get('stories_processed', 0)
            api_calls = entry.get('api_calls', 0)
            errors = len(entry.get('errors', []))

            lines.append(
                f"| {timestamp} | {operation} | {result} | {duration} | {stories} | {api_calls} | {errors} |"
            )

        lines.append("")

        return "\n".join(lines)

    def _render_metrics_markdown(self, report: Dict[str, Any]) -> str:
        """Render metrics as Markdown."""
        lines = []
        lines.append("# Performance Metrics")
        lines.append("")
        lines.append(f"**Period:** Last {report['period_days']} days")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Total Operations:** {report['total_operations']}")

        if report['avg_duration_ms']:
            avg_sec = report['avg_duration_ms'] / 1000
            lines.append(f"- **Average Duration:** {avg_sec:.2f}s")

        if report['avg_throughput']:
            lines.append(f"- **Average Throughput:** {report['avg_throughput']:.2f} stories/sec")

        lines.append(f"- **Total API Calls:** {report['total_api_calls']}")
        lines.append(f"- **Average API Calls/Sync:** {report['avg_api_calls_per_sync']:.1f}")
        lines.append("")

        # Bottlenecks
        if report['common_bottlenecks']:
            lines.append("## Common Bottlenecks")
            lines.append("")
            for bn in report['common_bottlenecks']:
                lines.append(f"- **{bn['type']}:** {bn['occurrences']} occurrences")
            lines.append("")

        return "\n".join(lines)

    def _render_full_report_markdown(self, days: int) -> str:
        """Render full report as Markdown."""
        lines = []
        lines.append("# BMAD Sync Full Report")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Period:** Last {days} days")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Dashboard
        lines.append(self._render_dashboard_markdown())
        lines.append("")
        lines.append("---")
        lines.append("")

        # Trends
        trends = self.history.get_trend_analysis(days=days)
        lines.append("# Sync Trends")
        lines.append("")
        lines.append(f"- **Total Syncs:** {trends['total_syncs']}")
        lines.append(f"- **Success Rate:** {trends['success_rate']}%")

        if trends['avg_duration_ms']:
            avg_sec = trends['avg_duration_ms'] / 1000
            lines.append(f"- **Average Duration:** {avg_sec:.2f}s")

        lines.append(f"- **Average Stories/Sync:** {trends['avg_stories_per_sync']}")
        lines.append(f"- **Total API Calls:** {trends['total_api_calls']}")
        lines.append(f"- **Total Errors:** {trends['total_errors']}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Metrics
        lines.append(self._render_metrics_markdown(
            self.metrics.get_performance_report(days=days)
        ))

        return "\n".join(lines)

    def _export_history_csv(self, history: List[Dict[str, Any]], output_path: Path) -> None:
        """Export history to CSV."""
        fieldnames = [
            'timestamp',
            'operation',
            'result',
            'duration_ms',
            'stories_processed',
            'api_calls',
            'error_count'
        ]

        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for entry in history:
                row = {
                    'timestamp': entry.get('timestamp', ''),
                    'operation': entry.get('operation', ''),
                    'result': entry.get('result', ''),
                    'duration_ms': entry.get('duration_ms', ''),
                    'stories_processed': entry.get('stories_processed', 0),
                    'api_calls': entry.get('api_calls', 0),
                    'error_count': len(entry.get('errors', []))
                }
                writer.writerow(row)


def export_report(
    report_type: str,
    output_path: Path,
    format: str = 'json',
    **kwargs
) -> None:
    """
    Export report (convenience function).

    Args:
        report_type: Type of report ('dashboard', 'history', 'metrics', 'full')
        output_path: Output file path
        format: Export format
        **kwargs: Additional parameters
    """
    exporter = ReportExporter()

    if report_type == 'dashboard':
        exporter.export_dashboard(output_path, format=format)
    elif report_type == 'history':
        exporter.export_history(output_path, format=format, **kwargs)
    elif report_type == 'metrics':
        exporter.export_metrics(output_path, format=format, **kwargs)
    elif report_type == 'full':
        exporter.export_full_report(output_path, format=format, **kwargs)


if __name__ == '__main__':
    # Demo export
    exporter = ReportExporter()

    # Export full report
    output = Path('bmad_sync_report.md')
    exporter.export_full_report(output, format='markdown', days=7)
    print(f"Report exported to: {output}")
