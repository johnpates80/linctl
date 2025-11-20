#!/usr/bin/env python3
"""
Real-time status dashboard for BMAD sync system.

Provides status aggregation, health scores, and monitoring capabilities.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

from state_manager import StateManager
from health import compute_health
from validator import validate_all


@dataclass
class ProjectStatus:
    """Status information for a single project."""
    project_name: str
    last_sync: Optional[str]
    health_score: int
    health_status: str
    active_conflicts: int
    recent_errors: int
    stories_synced: int
    sync_duration_ms: Optional[int]
    linear_issue_count: int


class Dashboard:
    """Real-time status dashboard for BMAD sync monitoring."""

    def __init__(self, state_manager: Optional[StateManager] = None):
        """
        Initialize dashboard.

        Args:
            state_manager: Optional state manager instance
        """
        self.state_manager = state_manager or StateManager()
        self.conflicts_dir = self.state_manager.state_dir.parent / 'conflicts'
        self.history_dir = self.state_manager.state_dir.parent / 'history'

    def get_project_status(self) -> ProjectStatus:
        """
        Get current project status.

        Returns:
            ProjectStatus object with aggregated information
        """
        # Get health information
        health_data = compute_health()

        # Get sync state
        sync_state = self.state_manager.get_sync_state()
        last_sync = sync_state.get('last_sync')

        # Count recent errors (last 24 hours)
        recent_errors = self._count_recent_errors(sync_state, hours=24)

        # Count active conflicts
        active_conflicts = self._count_active_conflicts()

        # Get Linear issue count
        number_registry = self.state_manager.get_number_registry()
        linear_issue_count = len(number_registry)

        # Get last sync duration
        last_duration_ms = self._get_last_sync_duration(sync_state)

        # Get stories synced count
        content_index = self.state_manager.get_content_index()
        stories_synced = len(content_index.get('stories', {}))

        # Determine project name
        project_name = self._get_project_name()

        return ProjectStatus(
            project_name=project_name,
            last_sync=last_sync,
            health_score=health_data['score'],
            health_status=health_data['status'],
            active_conflicts=active_conflicts,
            recent_errors=recent_errors,
            stories_synced=stories_synced,
            sync_duration_ms=last_duration_ms,
            linear_issue_count=linear_issue_count
        )

    def render_dashboard(self, detailed: bool = False) -> str:
        """
        Render dashboard as formatted text.

        Args:
            detailed: Include detailed diagnostics

        Returns:
            Formatted dashboard text
        """
        status = self.get_project_status()

        lines = []
        lines.append("=" * 60)
        lines.append(f"  BMAD Sync Dashboard - {status.project_name}")
        lines.append("=" * 60)
        lines.append("")

        # Health section
        health_icon = self._get_health_icon(status.health_status)
        lines.append(f"Health: {health_icon} {status.health_status} ({status.health_score}/100)")
        lines.append("")

        # Sync status
        if status.last_sync:
            time_ago = self._format_time_ago(status.last_sync)
            lines.append(f"Last Sync: {time_ago}")
            if status.sync_duration_ms:
                duration_sec = status.sync_duration_ms / 1000
                lines.append(f"Duration: {duration_sec:.2f}s")
        else:
            lines.append("Last Sync: Never")
        lines.append("")

        # Metrics
        lines.append("Metrics:")
        lines.append(f"  Stories Tracked: {status.stories_synced}")
        lines.append(f"  Linear Issues: {status.linear_issue_count}")
        lines.append(f"  Active Conflicts: {self._colorize_count(status.active_conflicts)}")
        lines.append(f"  Recent Errors (24h): {self._colorize_count(status.recent_errors)}")
        lines.append("")

        # Detailed diagnostics
        if detailed:
            health_data = compute_health()
            diagnostics = health_data.get('diagnostics', {})

            lines.append("Detailed Diagnostics:")
            lines.append(f"  Validation: {self._check_icon(diagnostics.get('validation', {}).get('ok', False))}")
            lines.append(f"  State Files: {self._check_icon(diagnostics.get('state_files_ok', False))}")
            lines.append(f"  Permissions: {self._check_icon(diagnostics.get('state_permissions_ok', False))}")

            linctl = diagnostics.get('linctl', {})
            lines.append(f"  linctl Installed: {self._check_icon(linctl.get('installed', False))}")
            lines.append(f"  linctl Authenticated: {self._check_icon(linctl.get('authenticated', False))}")
            lines.append("")

        lines.append("=" * 60)

        return "\n".join(lines)

    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Get dashboard data as dictionary.

        Returns:
            Dictionary with dashboard information
        """
        status = self.get_project_status()
        health_data = compute_health()

        return {
            'project': asdict(status),
            'health': health_data,
            'timestamp': datetime.now().isoformat()
        }

    def _count_recent_errors(self, sync_state: Dict[str, Any], hours: int = 24) -> int:
        """Count errors in the last N hours."""
        errors = sync_state.get('errors', [])
        if not errors:
            return 0

        cutoff = datetime.now() - timedelta(hours=hours)
        count = 0

        for error in errors:
            timestamp_str = error.get('timestamp', '')
            if timestamp_str:
                try:
                    error_time = datetime.fromisoformat(timestamp_str)
                    if error_time >= cutoff:
                        count += 1
                except (ValueError, TypeError):
                    continue

        return count

    def _count_active_conflicts(self) -> int:
        """Count active conflicts."""
        pending_file = self.conflicts_dir / 'pending.json'

        if not pending_file.exists():
            return 0

        try:
            with open(pending_file, 'r') as f:
                conflicts = json.load(f)
                return len(conflicts) if isinstance(conflicts, list) else 0
        except Exception:
            return 0

    def _get_last_sync_duration(self, sync_state: Dict[str, Any]) -> Optional[int]:
        """Get last sync duration in milliseconds."""
        operations = sync_state.get('operations', [])
        if not operations:
            return None

        last_op = operations[-1]
        details = last_op.get('details', {})
        return details.get('duration_ms')

    def _get_project_name(self) -> str:
        """Get project name from config."""
        try:
            config_file = Path('bmad/bmm/config.yaml')
            if config_file.exists():
                content = config_file.read_text()
                for line in content.split('\n'):
                    if line.startswith('project_name:'):
                        return line.split(':', 1)[1].strip()
        except Exception:
            pass

        return Path.cwd().name

    def _get_health_icon(self, status: str) -> str:
        """Get icon for health status."""
        icons = {
            'OK': '✅',
            'DEGRADED': '⚠️',
            'POOR': '❌'
        }
        return icons.get(status, '❓')

    def _check_icon(self, ok: bool) -> str:
        """Get check/cross icon."""
        return '✅' if ok else '❌'

    def _colorize_count(self, count: int) -> str:
        """Add visual indicator for counts."""
        if count == 0:
            return f"{count} ✅"
        elif count < 5:
            return f"{count} ⚠️"
        else:
            return f"{count} ❌"

    def _format_time_ago(self, timestamp_str: str) -> str:
        """Format timestamp as time ago."""
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            delta = datetime.now() - timestamp

            if delta.total_seconds() < 60:
                return f"{int(delta.total_seconds())}s ago"
            elif delta.total_seconds() < 3600:
                return f"{int(delta.total_seconds() / 60)}m ago"
            elif delta.total_seconds() < 86400:
                return f"{int(delta.total_seconds() / 3600)}h ago"
            else:
                return f"{int(delta.total_seconds() / 86400)}d ago"
        except (ValueError, TypeError):
            return timestamp_str

    def watch_mode(self, interval_seconds: int = 5):
        """
        Run dashboard in watch mode (auto-refresh).

        Args:
            interval_seconds: Refresh interval in seconds
        """
        import time
        import os

        try:
            while True:
                # Clear screen
                os.system('clear' if os.name != 'nt' else 'cls')

                # Render dashboard
                print(self.render_dashboard(detailed=True))
                print(f"\nRefreshing every {interval_seconds}s... (Ctrl+C to exit)")

                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print("\n\nDashboard closed.")


def render_dashboard(detailed: bool = False) -> str:
    """
    Render dashboard (convenience function).

    Args:
        detailed: Include detailed diagnostics

    Returns:
        Formatted dashboard text
    """
    dashboard = Dashboard()
    return dashboard.render_dashboard(detailed=detailed)


if __name__ == '__main__':
    # Demo dashboard
    dashboard = Dashboard()
    print(dashboard.render_dashboard(detailed=True))
