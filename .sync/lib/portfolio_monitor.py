#!/usr/bin/env python3
"""
Portfolio Monitoring and Health Tracking.

Centralized monitoring dashboard for portfolio-wide project health,
sync status overview, and alert system.
"""

import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import json

from portfolio_config import PortfolioConfig, load_portfolio_config
from health import compute_health


@dataclass
class ProjectHealth:
    """Health status for a single project."""
    project_key: str
    project_name: str
    health_score: int  # 0-100
    status: str  # OK, WARNING, ERROR
    last_sync: Optional[str] = None
    issues: List[str] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PortfolioHealth:
    """Aggregate health status for entire portfolio."""
    overall_score: int  # 0-100
    overall_status: str  # OK, WARNING, ERROR
    total_projects: int
    healthy_projects: int
    warning_projects: int
    error_projects: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    project_healths: List[ProjectHealth] = field(default_factory=list)
    alerts: List[Dict[str, Any]] = field(default_factory=list)


class PortfolioMonitor:
    """Monitor health and status across portfolio projects."""

    def __init__(self, portfolio_config: Optional[PortfolioConfig] = None):
        """
        Initialize portfolio monitor.

        Args:
            portfolio_config: Portfolio configuration (auto-loaded if None)
        """
        self.portfolio_config = portfolio_config or load_portfolio_config()

    def check_project_health(self, project_path: Path) -> ProjectHealth:
        """
        Check health of a single project.

        Args:
            project_path: Path to project root

        Returns:
            ProjectHealth status
        """
        import os
        original_dir = Path.cwd()

        try:
            os.chdir(project_path)
            health_report = compute_health()

            project_health = ProjectHealth(
                project_key=project_path.name,
                project_name=project_path.name,
                health_score=health_report.get('score', 0),
                status=health_report.get('status', 'UNKNOWN'),
                diagnostics=health_report.get('diagnostics', {})
            )

            # Extract issues
            diagnostics = health_report.get('diagnostics', {})
            if not diagnostics.get('validation', {}).get('ok', False):
                project_health.issues.append("Validation issues detected")
            if not diagnostics.get('state_files_ok'):
                project_health.issues.append("State files missing or corrupt")
            if not diagnostics.get('state_permissions_ok'):
                project_health.issues.append("State directory permissions too open")

            linctl = diagnostics.get('linctl', {})
            if not linctl.get('installed'):
                project_health.issues.append("linctl not installed")
            elif not linctl.get('authenticated'):
                project_health.issues.append("linctl not authenticated")

            # Get last sync time from state
            try:
                state_file = project_path / '.sync' / 'state' / 'sync_state.json'
                if state_file.exists():
                    with open(state_file) as f:
                        state = json.load(f)
                        project_health.last_sync = state.get('last_sync')
            except Exception:
                pass

            os.chdir(original_dir)
            return project_health

        except Exception as e:
            os.chdir(original_dir)
            return ProjectHealth(
                project_key=project_path.name,
                project_name=project_path.name,
                health_score=0,
                status='ERROR',
                issues=[f"Health check failed: {str(e)}"]
            )

    def check_portfolio_health(self, enabled_only: bool = True) -> PortfolioHealth:
        """
        Check health across all portfolio projects.

        Args:
            enabled_only: Only check enabled projects

        Returns:
            PortfolioHealth with aggregate status
        """
        projects = self.portfolio_config.list_projects(enabled_only=enabled_only)

        if not projects:
            return PortfolioHealth(
                overall_score=0,
                overall_status='UNKNOWN',
                total_projects=0,
                healthy_projects=0,
                warning_projects=0,
                error_projects=0
            )

        project_healths = []
        for project in projects:
            health = self.check_project_health(Path(project['path']))
            health.project_key = project['key']
            health.project_name = project['name']
            project_healths.append(health)

        # Calculate aggregate metrics
        healthy = sum(1 for h in project_healths if h.status == 'OK')
        warning = sum(1 for h in project_healths if h.status == 'WARNING')
        error = sum(1 for h in project_healths if h.status == 'ERROR')

        avg_score = sum(h.health_score for h in project_healths) // len(project_healths)

        # Overall status based on worst case
        if error > 0:
            overall_status = 'ERROR'
        elif warning > 0:
            overall_status = 'WARNING'
        else:
            overall_status = 'OK'

        # Generate alerts for problematic projects
        alerts = []
        for health in project_healths:
            if health.status != 'OK':
                alerts.append({
                    'project': health.project_key,
                    'severity': 'high' if health.status == 'ERROR' else 'medium',
                    'message': f"{health.project_name}: {', '.join(health.issues)}",
                    'timestamp': datetime.now().isoformat()
                })

        return PortfolioHealth(
            overall_score=avg_score,
            overall_status=overall_status,
            total_projects=len(projects),
            healthy_projects=healthy,
            warning_projects=warning,
            error_projects=error,
            project_healths=project_healths,
            alerts=alerts
        )

    def render_dashboard(self, detailed: bool = False) -> str:
        """
        Render portfolio health dashboard as text.

        Args:
            detailed: Include detailed per-project diagnostics

        Returns:
            Formatted dashboard string
        """
        portfolio_health = self.check_portfolio_health()

        lines = [
            "=" * 70,
            f"PORTFOLIO HEALTH DASHBOARD ({portfolio_health.timestamp})",
            "=" * 70,
            f"Overall Status: {portfolio_health.overall_status} (Score: {portfolio_health.overall_score}/100)",
            f"Projects: {portfolio_health.healthy_projects}/{portfolio_health.total_projects} healthy, "
            f"{portfolio_health.warning_projects} warnings, {portfolio_health.error_projects} errors",
            ""
        ]

        # Alerts section
        if portfolio_health.alerts:
            lines.append("⚠️  ALERTS:")
            lines.append("-" * 70)
            for alert in portfolio_health.alerts:
                severity_icon = "🔴" if alert['severity'] == 'high' else "🟡"
                lines.append(f"{severity_icon} {alert['message']}")
            lines.append("")

        # Project status overview
        lines.append("PROJECT STATUS:")
        lines.append("-" * 70)

        for health in portfolio_health.project_healths:
            if health.status == 'OK':
                status_icon = "✅"
            elif health.status == 'WARNING':
                status_icon = "⚠️ "
            else:
                status_icon = "❌"

            lines.append(f"{status_icon} {health.project_name} ({health.project_key})")
            lines.append(f"   Score: {health.health_score}/100")

            if health.last_sync:
                lines.append(f"   Last Sync: {health.last_sync}")

            if health.issues:
                lines.append(f"   Issues: {len(health.issues)}")
                if detailed:
                    for issue in health.issues:
                        lines.append(f"     • {issue}")

            lines.append("")

        lines.append("=" * 70)

        return "\n".join(lines)


def format_portfolio_health(health: PortfolioHealth, detailed: bool = False) -> str:
    """
    Format portfolio health as human-readable text.

    Args:
        health: PortfolioHealth to format
        detailed: Include detailed diagnostics

    Returns:
        Formatted string
    """
    monitor = PortfolioMonitor()
    return monitor.render_dashboard(detailed=detailed)


if __name__ == '__main__':
    # CLI testing interface
    import argparse

    parser = argparse.ArgumentParser(description='Portfolio health monitoring')
    parser.add_argument('--detailed', action='store_true', help='Show detailed diagnostics')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    try:
        monitor = PortfolioMonitor()
        health = monitor.check_portfolio_health()

        if args.json:
            output = {
                'overall_score': health.overall_score,
                'overall_status': health.overall_status,
                'projects': {
                    'total': health.total_projects,
                    'healthy': health.healthy_projects,
                    'warning': health.warning_projects,
                    'error': health.error_projects
                },
                'alerts': health.alerts,
                'project_healths': [
                    {
                        'key': ph.project_key,
                        'name': ph.project_name,
                        'score': ph.health_score,
                        'status': ph.status,
                        'last_sync': ph.last_sync,
                        'issues': ph.issues
                    }
                    for ph in health.project_healths
                ]
            }
            print(json.dumps(output, indent=2))
        else:
            print(monitor.render_dashboard(detailed=args.detailed))

        sys.exit(0 if health.overall_status == 'OK' else 1)

    except Exception as e:
        print(f"✗ Monitoring failed: {e}", file=sys.stderr)
        sys.exit(1)
