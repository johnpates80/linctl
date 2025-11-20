#!/usr/bin/env python3
"""
Portfolio Scheduling and Automation.

Cron-based scheduling for automated portfolio sync operations with
per-project schedules and configurable intervals.
"""

import sys
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import json

from portfolio_config import PortfolioConfig, load_portfolio_config


class PortfolioScheduler:
    """Manage scheduled sync operations for portfolio projects."""

    def __init__(self, portfolio_config: Optional[PortfolioConfig] = None):
        """
        Initialize portfolio scheduler.

        Args:
            portfolio_config: Portfolio configuration (auto-loaded if None)
        """
        self.portfolio_config = portfolio_config or load_portfolio_config()
        self.cron_comment = "# BMAD Portfolio Sync"

    def get_cron_entries(self) -> List[str]:
        """
        Get existing BMAD portfolio cron entries.

        Returns:
            List of cron entry lines
        """
        try:
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            if result.returncode != 0:
                return []

            lines = result.stdout.strip().split('\n')
            # Filter for BMAD portfolio entries
            bmad_entries = []
            for i, line in enumerate(lines):
                if self.cron_comment in line or (
                    i > 0 and self.cron_comment in lines[i-1] and 'bmad-portfolio sync' in line
                ):
                    bmad_entries.append(line)

            return bmad_entries

        except Exception:
            return []

    def create_schedule(self, interval: str = '0 */6 * * *',
                       projects: Optional[List[str]] = None,
                       options: Optional[List[str]] = None) -> bool:
        """
        Create or update cron schedule for portfolio sync.

        Args:
            interval: Cron schedule expression (default: every 6 hours)
            projects: Specific project keys to sync (None = all)
            options: Additional CLI options (e.g., ['--workers', '8'])

        Returns:
            True if schedule created successfully

        Raises:
            RuntimeError: If cron update fails
        """
        try:
            # Get existing crontab
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            existing_lines = result.stdout.strip().split('\n') if result.returncode == 0 else []

            # Remove old BMAD portfolio entries
            filtered_lines = []
            skip_next = False
            for i, line in enumerate(existing_lines):
                if self.cron_comment in line:
                    skip_next = True
                    continue
                if skip_next and 'bmad-portfolio sync' in line:
                    skip_next = False
                    continue
                if line.strip():  # Keep non-empty lines
                    filtered_lines.append(line)

            # Build new cron command
            cmd_parts = ['bmad-portfolio', 'sync']
            if projects:
                cmd_parts.extend(['--projects'] + projects)
            if options:
                cmd_parts.extend(options)

            command = ' '.join(cmd_parts)

            # Add new entry
            new_entry = f"{self.cron_comment}\n{interval} {command} >> /tmp/bmad-portfolio-sync.log 2>&1"

            # Write updated crontab
            new_crontab = '\n'.join(filtered_lines + [new_entry, ''])

            process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
            process.communicate(input=new_crontab)

            if process.returncode != 0:
                raise RuntimeError("Failed to update crontab")

            return True

        except Exception as e:
            raise RuntimeError(f"Failed to create schedule: {e}")

    def remove_schedule(self) -> bool:
        """
        Remove portfolio sync schedule from cron.

        Returns:
            True if schedule removed successfully
        """
        try:
            # Get existing crontab
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            if result.returncode != 0:
                return True  # No crontab exists

            existing_lines = result.stdout.strip().split('\n')

            # Remove BMAD portfolio entries
            filtered_lines = []
            skip_next = False
            for i, line in enumerate(existing_lines):
                if self.cron_comment in line:
                    skip_next = True
                    continue
                if skip_next and 'bmad-portfolio sync' in line:
                    skip_next = False
                    continue
                if line.strip():
                    filtered_lines.append(line)

            # Write updated crontab
            if filtered_lines:
                new_crontab = '\n'.join(filtered_lines + [''])
                process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
                process.communicate(input=new_crontab)
            else:
                # Remove crontab entirely if empty
                subprocess.run(['crontab', '-r'], check=False)

            return True

        except Exception:
            return False

    def update_project_schedule(self, project_key: str, schedule: Optional[str]) -> None:
        """
        Update schedule configuration for a specific project.

        Args:
            project_key: Project identifier
            schedule: Cron schedule expression (None to disable)
        """
        schedules = self.portfolio_config.config.get('schedules', {})

        if schedule:
            schedules[project_key] = {
                'interval': schedule,
                'enabled': True,
                'updated': datetime.now().isoformat()
            }
        else:
            schedules.pop(project_key, None)

        self.portfolio_config.config['schedules'] = schedules
        self.portfolio_config.save()

    def get_project_schedule(self, project_key: str) -> Optional[Dict[str, Any]]:
        """
        Get schedule configuration for a project.

        Args:
            project_key: Project identifier

        Returns:
            Schedule configuration or None
        """
        schedules = self.portfolio_config.config.get('schedules', {})
        return schedules.get(project_key)

    def list_schedules(self) -> Dict[str, Any]:
        """
        List all project schedules.

        Returns:
            Dictionary of project schedules
        """
        schedules = self.portfolio_config.config.get('schedules', {})
        cron_entries = self.get_cron_entries()

        return {
            'project_schedules': schedules,
            'active_cron_jobs': cron_entries,
            'cron_available': self._is_cron_available()
        }

    def _is_cron_available(self) -> bool:
        """Check if cron is available on the system."""
        try:
            result = subprocess.run(['which', 'crontab'], capture_output=True)
            return result.returncode == 0
        except Exception:
            return False


def format_schedules(schedules: Dict[str, Any]) -> str:
    """
    Format schedule information as human-readable text.

    Args:
        schedules: Schedule data from list_schedules()

    Returns:
        Formatted string
    """
    lines = [
        "=" * 60,
        "PORTFOLIO SYNC SCHEDULES",
        "=" * 60
    ]

    if not schedules['cron_available']:
        lines.append("⚠️  Cron not available on this system")
        lines.append("")

    project_schedules = schedules.get('project_schedules', {})
    if project_schedules:
        lines.append("Project Schedules:")
        lines.append("-" * 60)
        for project_key, config in project_schedules.items():
            status = "✓" if config.get('enabled', True) else "✗"
            lines.append(f"{status} {project_key}")
            lines.append(f"   Interval: {config.get('interval')}")
            lines.append(f"   Updated: {config.get('updated', 'N/A')}")
            lines.append("")
    else:
        lines.append("No project-specific schedules configured")
        lines.append("")

    active_cron = schedules.get('active_cron_jobs', [])
    if active_cron:
        lines.append("Active Cron Jobs:")
        lines.append("-" * 60)
        for entry in active_cron:
            lines.append(f"  {entry}")
        lines.append("")
    else:
        lines.append("No active cron jobs")
        lines.append("")

    lines.append("=" * 60)

    return "\n".join(lines)


if __name__ == '__main__':
    # CLI testing interface
    import argparse

    parser = argparse.ArgumentParser(description='Portfolio scheduling')
    subparsers = parser.add_subparsers(dest='command', required=True)

    # create command
    create = subparsers.add_parser('create', help='Create cron schedule')
    create.add_argument('--interval', default='0 */6 * * *',
                       help='Cron interval (default: every 6 hours)')
    create.add_argument('--projects', nargs='+', help='Specific projects to sync')
    create.add_argument('--workers', type=int, help='Number of workers')

    # remove command
    subparsers.add_parser('remove', help='Remove cron schedule')

    # list command
    subparsers.add_parser('list', help='List schedules')

    # project command
    project = subparsers.add_parser('project', help='Manage project schedule')
    project.add_argument('project_key', help='Project identifier')
    project.add_argument('--interval', help='Cron interval (or None to disable)')

    args = parser.parse_args()

    try:
        scheduler = PortfolioScheduler()

        if args.command == 'create':
            options = []
            if args.workers:
                options.extend(['--workers', str(args.workers)])

            scheduler.create_schedule(
                interval=args.interval,
                projects=args.projects,
                options=options
            )
            print(f"✓ Schedule created: {args.interval}")

        elif args.command == 'remove':
            scheduler.remove_schedule()
            print("✓ Schedule removed")

        elif args.command == 'list':
            schedules = scheduler.list_schedules()
            print(format_schedules(schedules))

        elif args.command == 'project':
            interval = None if args.interval == 'None' else args.interval
            scheduler.update_project_schedule(args.project_key, interval)
            if interval:
                print(f"✓ Project schedule updated: {args.project_key} → {interval}")
            else:
                print(f"✓ Project schedule disabled: {args.project_key}")

        sys.exit(0)

    except Exception as e:
        print(f"✗ Scheduling failed: {e}", file=sys.stderr)
        sys.exit(1)
