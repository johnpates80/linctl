#!/usr/bin/env python3
"""
Portfolio Analytics and Reporting.

Aggregate metrics, trend analysis, and export capabilities for portfolio management.
"""

import sys
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import csv

from portfolio_config import PortfolioConfig, load_portfolio_config
from history import HistoryTracker
from metrics import MetricsCollector


@dataclass
class PortfolioMetrics:
    """Aggregate metrics across portfolio."""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    total_projects: int = 0
    total_stories_synced: int = 0
    total_operations: int = 0
    total_duration_seconds: float = 0.0
    avg_sync_duration: float = 0.0
    error_rate: float = 0.0
    portfolio_health_score: int = 0
    project_metrics: List[Dict[str, Any]] = field(default_factory=list)


class PortfolioAnalytics:
    """Analytics engine for portfolio-wide insights."""

    def __init__(self, portfolio_config: Optional[PortfolioConfig] = None):
        """
        Initialize portfolio analytics.

        Args:
            portfolio_config: Portfolio configuration (auto-loaded if None)
        """
        self.portfolio_config = portfolio_config or load_portfolio_config()

    def collect_project_metrics(self, project_path: Path, days: int = 30) -> Dict[str, Any]:
        """
        Collect metrics for a single project.

        Args:
            project_path: Path to project root
            days: Number of days of history to analyze

        Returns:
            Project metrics dictionary
        """
        import os
        original_dir = Path.cwd()

        try:
            os.chdir(project_path)

            # Collect metrics using existing collectors
            metrics_collector = MetricsCollector()
            history_tracker = HistoryTracker()

            # Get performance metrics
            performance = metrics_collector.get_performance_metrics(days=days)

            # Get historical data
            recent_syncs = history_tracker.get_recent_syncs(days=days)

            metrics = {
                'project_path': str(project_path),
                'total_syncs': len(recent_syncs),
                'total_operations': sum(s.get('operations', 0) for s in recent_syncs),
                'avg_duration': performance.get('avg_duration', 0),
                'error_count': sum(s.get('errors', 0) for s in recent_syncs),
                'conflict_count': sum(s.get('conflicts', 0) for s in recent_syncs),
                'last_sync': recent_syncs[0].get('timestamp') if recent_syncs else None
            }

            os.chdir(original_dir)
            return metrics

        except Exception as e:
            os.chdir(original_dir)
            return {
                'project_path': str(project_path),
                'error': str(e)
            }

    def aggregate_metrics(self, days: int = 30) -> PortfolioMetrics:
        """
        Aggregate metrics across all projects.

        Args:
            days: Number of days of history to analyze

        Returns:
            PortfolioMetrics with portfolio-wide statistics
        """
        projects = self.portfolio_config.list_projects(enabled_only=True)

        if not projects:
            return PortfolioMetrics()

        project_metrics = []
        total_stories = 0
        total_ops = 0
        total_duration = 0.0
        total_errors = 0

        for project in projects:
            metrics = self.collect_project_metrics(Path(project['path']), days=days)
            metrics['key'] = project['key']
            metrics['name'] = project['name']
            project_metrics.append(metrics)

            if 'error' not in metrics:
                total_stories += metrics.get('total_syncs', 0)
                total_ops += metrics.get('total_operations', 0)
                total_duration += metrics.get('avg_duration', 0) * metrics.get('total_syncs', 0)
                total_errors += metrics.get('error_count', 0)

        avg_duration = total_duration / total_stories if total_stories > 0 else 0.0
        error_rate = (total_errors / total_ops * 100) if total_ops > 0 else 0.0

        return PortfolioMetrics(
            total_projects=len(projects),
            total_stories_synced=total_stories,
            total_operations=total_ops,
            total_duration_seconds=total_duration,
            avg_sync_duration=avg_duration,
            error_rate=error_rate,
            project_metrics=project_metrics
        )

    def analyze_trends(self, days: int = 30) -> Dict[str, Any]:
        """
        Analyze trends across portfolio.

        Args:
            days: Number of days to analyze

        Returns:
            Trend analysis dictionary
        """
        metrics = self.aggregate_metrics(days=days)

        # Calculate trends
        trends = {
            'period_days': days,
            'total_activity': metrics.total_stories_synced,
            'avg_daily_syncs': metrics.total_stories_synced / days if days > 0 else 0,
            'operational_efficiency': {
                'avg_sync_duration': metrics.avg_sync_duration,
                'error_rate': metrics.error_rate,
                'total_operations': metrics.total_operations
            },
            'project_activity': [
                {
                    'name': pm['name'],
                    'syncs': pm.get('total_syncs', 0),
                    'operations': pm.get('total_operations', 0),
                    'errors': pm.get('error_count', 0)
                }
                for pm in metrics.project_metrics
                if 'error' not in pm
            ]
        }

        return trends

    def export_report(self, output_path: Path, format: str = 'json', days: int = 30) -> None:
        """
        Export portfolio analytics report.

        Args:
            output_path: Path to output file
            format: Export format (json, markdown, csv)
            days: Number of days to include in report

        Raises:
            ValueError: If format is unsupported
        """
        metrics = self.aggregate_metrics(days=days)
        trends = self.analyze_trends(days=days)

        if format == 'json':
            report = {
                'generated': datetime.now().isoformat(),
                'period_days': days,
                'metrics': {
                    'total_projects': metrics.total_projects,
                    'total_stories_synced': metrics.total_stories_synced,
                    'total_operations': metrics.total_operations,
                    'avg_sync_duration': metrics.avg_sync_duration,
                    'error_rate': metrics.error_rate
                },
                'trends': trends,
                'projects': metrics.project_metrics
            }
            output_path.write_text(json.dumps(report, indent=2))

        elif format == 'markdown':
            lines = [
                f"# Portfolio Analytics Report",
                f"",
                f"**Generated:** {datetime.now().isoformat()}",
                f"**Period:** {days} days",
                f"",
                f"## Summary",
                f"",
                f"- **Projects:** {metrics.total_projects}",
                f"- **Stories Synced:** {metrics.total_stories_synced}",
                f"- **Operations:** {metrics.total_operations}",
                f"- **Avg Sync Duration:** {metrics.avg_sync_duration:.2f}s",
                f"- **Error Rate:** {metrics.error_rate:.2f}%",
                f"",
                f"## Project Activity",
                f"",
                f"| Project | Syncs | Operations | Errors |",
                f"|---------|-------|------------|--------|"
            ]

            for pm in metrics.project_metrics:
                if 'error' not in pm:
                    lines.append(
                        f"| {pm['name']} | {pm.get('total_syncs', 0)} | "
                        f"{pm.get('total_operations', 0)} | {pm.get('error_count', 0)} |"
                    )

            output_path.write_text("\n".join(lines))

        elif format == 'csv':
            with open(output_path, 'w', newline='') as csvfile:
                fieldnames = ['project', 'syncs', 'operations', 'errors', 'conflicts', 'avg_duration']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for pm in metrics.project_metrics:
                    if 'error' not in pm:
                        writer.writerow({
                            'project': pm['name'],
                            'syncs': pm.get('total_syncs', 0),
                            'operations': pm.get('total_operations', 0),
                            'errors': pm.get('error_count', 0),
                            'conflicts': pm.get('conflict_count', 0),
                            'avg_duration': pm.get('avg_duration', 0)
                        })

        else:
            raise ValueError(f"Unsupported export format: {format}")


if __name__ == '__main__':
    # CLI testing interface
    import argparse

    parser = argparse.ArgumentParser(description='Portfolio analytics')
    parser.add_argument('--days', type=int, default=30, help='Days of history')
    parser.add_argument('--export', help='Export report to file')
    parser.add_argument('--format', choices=['json', 'markdown', 'csv'], default='json')
    parser.add_argument('--trends', action='store_true', help='Show trend analysis')

    args = parser.parse_args()

    try:
        analytics = PortfolioAnalytics()

        if args.trends:
            trends = analytics.analyze_trends(days=args.days)
            print(json.dumps(trends, indent=2))
        elif args.export:
            analytics.export_report(Path(args.export), format=args.format, days=args.days)
            print(f"✓ Report exported: {args.export}")
        else:
            metrics = analytics.aggregate_metrics(days=args.days)
            print(json.dumps({
                'total_projects': metrics.total_projects,
                'total_stories_synced': metrics.total_stories_synced,
                'total_operations': metrics.total_operations,
                'avg_sync_duration': metrics.avg_sync_duration,
                'error_rate': metrics.error_rate
            }, indent=2))

        sys.exit(0)

    except Exception as e:
        print(f"✗ Analytics failed: {e}", file=sys.stderr)
        sys.exit(1)
