#!/usr/bin/env python3
"""
Bulk Synchronization for Portfolio Management.

Execute sync operations across multiple BMAD projects in parallel,
with progress tracking, per-project error handling, and aggregate results.
"""

import sys
import time
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
import json

from portfolio_config import PortfolioConfig, load_portfolio_config
from sync_engine import SyncEngine
from logger import get_logger


@dataclass
class ProjectSyncResult:
    """Result of sync operation for a single project."""
    project_key: str
    project_name: str
    project_path: str
    success: bool
    operations_planned: int = 0
    operations_applied: int = 0
    operations_failed: int = 0
    conflicts: int = 0
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BulkSyncResult:
    """Aggregate result of bulk sync operation across portfolio."""
    total_projects: int
    successful_projects: int
    failed_projects: int
    total_operations: int
    total_applied: int
    total_failed: int
    total_conflicts: int
    duration_seconds: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    project_results: List[ProjectSyncResult] = field(default_factory=list)


class ProgressTracker:
    """Thread-safe progress tracker for bulk operations."""

    def __init__(self, total_projects: int):
        self.total_projects = total_projects
        self.completed = 0
        self.in_progress = []
        self.lock = threading.Lock()
        self.logger = get_logger()

    def start_project(self, project_key: str) -> None:
        """Mark project as started."""
        with self.lock:
            self.in_progress.append(project_key)
            self.logger.info(f"[{self.completed + 1}/{self.total_projects}] Starting: {project_key}")

    def complete_project(self, project_key: str, success: bool) -> None:
        """Mark project as completed."""
        with self.lock:
            if project_key in self.in_progress:
                self.in_progress.remove(project_key)
            self.completed += 1
            status = "✓" if success else "✗"
            self.logger.info(f"[{self.completed}/{self.total_projects}] {status} Completed: {project_key}")

    def get_progress(self) -> Dict[str, Any]:
        """Get current progress snapshot."""
        with self.lock:
            return {
                'total': self.total_projects,
                'completed': self.completed,
                'in_progress': len(self.in_progress),
                'remaining': self.total_projects - self.completed,
                'percent': round((self.completed / self.total_projects) * 100, 1) if self.total_projects > 0 else 0
            }


class BulkSyncEngine:
    """Execute sync operations across multiple projects in parallel."""

    def __init__(self, portfolio_config: Optional[PortfolioConfig] = None,
                 max_workers: int = 4, dry_run: bool = False):
        """
        Initialize bulk sync engine.

        Args:
            portfolio_config: Portfolio configuration (auto-loaded if None)
            max_workers: Maximum number of parallel workers
            dry_run: If True, only plan operations without applying
        """
        self.portfolio_config = portfolio_config or load_portfolio_config()
        self.max_workers = max_workers
        self.dry_run = dry_run
        self.logger = get_logger()

    def sync_project(self, project_key: str, project_config: Dict[str, Any],
                    progress_callback: Optional[Callable] = None) -> ProjectSyncResult:
        """
        Sync a single project.

        Args:
            project_key: Project identifier
            project_config: Project configuration
            progress_callback: Optional callback for progress updates

        Returns:
            ProjectSyncResult with operation details
        """
        project_path = Path(project_config['path'])
        project_name = project_config['name']
        start_time = time.time()

        result = ProjectSyncResult(
            project_key=project_key,
            project_name=project_name,
            project_path=str(project_path),
            success=False
        )

        try:
            # Change to project directory
            original_dir = Path.cwd()
            import os
            os.chdir(project_path)

            # Initialize sync engine for this project
            engine = SyncEngine(dry_run=self.dry_run)

            # Execute sync
            plan = engine.sync(force_refresh=False)
            operations = plan['operations']

            result.operations_planned = len(operations)
            result.details['report'] = plan.get('report', '')

            # Detect conflicts
            conflicts = engine.detect_and_record_conflicts(
                engine.discovery.discover_all(previous_index=None)
            )
            result.conflicts = len(conflicts) if conflicts else 0

            # Apply operations if not dry-run
            if not self.dry_run and operations:
                success, failed, messages = engine.apply(operations)
                result.operations_applied = success
                result.operations_failed = failed
                result.details['messages'] = messages
            else:
                result.operations_applied = 0
                result.operations_failed = 0

            result.success = True

            # Restore original directory
            os.chdir(original_dir)

        except Exception as e:
            self.logger.error(f"Sync failed for {project_key}: {e}")
            result.success = False
            result.error_message = str(e)

        result.duration_seconds = time.time() - start_time

        return result

    def sync_all(self, enabled_only: bool = True,
                progress_callback: Optional[Callable] = None) -> BulkSyncResult:
        """
        Sync all projects in portfolio.

        Args:
            enabled_only: Only sync enabled projects
            progress_callback: Optional callback for progress updates

        Returns:
            BulkSyncResult with aggregate statistics
        """
        start_time = time.time()

        # Get projects to sync
        projects = self.portfolio_config.list_projects(enabled_only=enabled_only)

        if not projects:
            self.logger.warning("No projects found in portfolio")
            return BulkSyncResult(
                total_projects=0,
                successful_projects=0,
                failed_projects=0,
                total_operations=0,
                total_applied=0,
                total_failed=0,
                total_conflicts=0,
                duration_seconds=0.0
            )

        self.logger.info(f"Starting bulk sync: {len(projects)} project(s)")

        # Initialize progress tracker
        progress = ProgressTracker(len(projects))

        # Execute sync operations in parallel
        project_results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all sync tasks
            future_to_project = {
                executor.submit(
                    self._sync_project_with_progress,
                    proj['key'],
                    proj,
                    progress,
                    progress_callback
                ): proj['key']
                for proj in projects
            }

            # Collect results as they complete
            for future in as_completed(future_to_project):
                project_key = future_to_project[future]
                try:
                    result = future.result()
                    project_results.append(result)
                except Exception as e:
                    self.logger.error(f"Unexpected error for {project_key}: {e}")
                    # Create failed result
                    proj = next(p for p in projects if p['key'] == project_key)
                    project_results.append(ProjectSyncResult(
                        project_key=project_key,
                        project_name=proj['name'],
                        project_path=proj['path'],
                        success=False,
                        error_message=str(e)
                    ))

        # Calculate aggregate statistics
        duration = time.time() - start_time

        bulk_result = BulkSyncResult(
            total_projects=len(projects),
            successful_projects=sum(1 for r in project_results if r.success),
            failed_projects=sum(1 for r in project_results if not r.success),
            total_operations=sum(r.operations_planned for r in project_results),
            total_applied=sum(r.operations_applied for r in project_results),
            total_failed=sum(r.operations_failed for r in project_results),
            total_conflicts=sum(r.conflicts for r in project_results),
            duration_seconds=duration,
            project_results=project_results
        )

        self.logger.info(
            f"Bulk sync complete: {bulk_result.successful_projects}/{bulk_result.total_projects} successful, "
            f"{bulk_result.total_applied} operations applied, "
            f"{bulk_result.duration_seconds:.2f}s"
        )

        return bulk_result

    def _sync_project_with_progress(self, project_key: str, project_config: Dict[str, Any],
                                    progress: ProgressTracker,
                                    progress_callback: Optional[Callable] = None) -> ProjectSyncResult:
        """Helper to sync project with progress tracking."""
        progress.start_project(project_key)

        if progress_callback:
            progress_callback(progress.get_progress())

        result = self.sync_project(project_key, project_config)

        progress.complete_project(project_key, result.success)

        if progress_callback:
            progress_callback(progress.get_progress())

        return result

    def sync_selective(self, project_keys: List[str],
                      progress_callback: Optional[Callable] = None) -> BulkSyncResult:
        """
        Sync specific projects by key.

        Args:
            project_keys: List of project keys to sync
            progress_callback: Optional callback for progress updates

        Returns:
            BulkSyncResult for selected projects
        """
        start_time = time.time()

        # Get selected projects
        all_projects = self.portfolio_config.list_projects()
        selected_projects = [
            p for p in all_projects
            if p['key'] in project_keys
        ]

        if not selected_projects:
            self.logger.warning(f"No matching projects found for keys: {project_keys}")
            return BulkSyncResult(
                total_projects=0,
                successful_projects=0,
                failed_projects=0,
                total_operations=0,
                total_applied=0,
                total_failed=0,
                total_conflicts=0,
                duration_seconds=0.0
            )

        self.logger.info(f"Starting selective sync: {len(selected_projects)} project(s)")

        # Initialize progress tracker
        progress = ProgressTracker(len(selected_projects))

        # Execute sync operations in parallel
        project_results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_project = {
                executor.submit(
                    self._sync_project_with_progress,
                    proj['key'],
                    proj,
                    progress,
                    progress_callback
                ): proj['key']
                for proj in selected_projects
            }

            for future in as_completed(future_to_project):
                project_key = future_to_project[future]
                try:
                    result = future.result()
                    project_results.append(result)
                except Exception as e:
                    self.logger.error(f"Unexpected error for {project_key}: {e}")
                    proj = next(p for p in selected_projects if p['key'] == project_key)
                    project_results.append(ProjectSyncResult(
                        project_key=project_key,
                        project_name=proj['name'],
                        project_path=proj['path'],
                        success=False,
                        error_message=str(e)
                    ))

        # Calculate aggregate statistics
        duration = time.time() - start_time

        return BulkSyncResult(
            total_projects=len(selected_projects),
            successful_projects=sum(1 for r in project_results if r.success),
            failed_projects=sum(1 for r in project_results if not r.success),
            total_operations=sum(r.operations_planned for r in project_results),
            total_applied=sum(r.operations_applied for r in project_results),
            total_failed=sum(r.operations_failed for r in project_results),
            total_conflicts=sum(r.conflicts for r in project_results),
            duration_seconds=duration,
            project_results=project_results
        )


def format_bulk_result(result: BulkSyncResult, detailed: bool = False) -> str:
    """
    Format bulk sync result as human-readable text.

    Args:
        result: BulkSyncResult to format
        detailed: Include per-project details

    Returns:
        Formatted string
    """
    lines = [
        "=" * 60,
        f"BULK SYNC RESULTS ({result.timestamp})",
        "=" * 60,
        f"Projects: {result.successful_projects}/{result.total_projects} successful",
        f"Operations: {result.total_applied} applied, {result.total_failed} failed",
        f"Conflicts: {result.total_conflicts}",
        f"Duration: {result.duration_seconds:.2f}s",
        ""
    ]

    if detailed and result.project_results:
        lines.append("Project Details:")
        lines.append("-" * 60)

        for proj_result in result.project_results:
            status = "✓" if proj_result.success else "✗"
            lines.append(f"\n{status} {proj_result.project_name} ({proj_result.project_key})")
            lines.append(f"  Path: {proj_result.project_path}")
            lines.append(f"  Operations: {proj_result.operations_applied}/{proj_result.operations_planned}")
            if proj_result.conflicts > 0:
                lines.append(f"  Conflicts: {proj_result.conflicts}")
            if proj_result.error_message:
                lines.append(f"  Error: {proj_result.error_message}")
            lines.append(f"  Duration: {proj_result.duration_seconds:.2f}s")

    lines.append("=" * 60)

    return "\n".join(lines)


if __name__ == '__main__':
    # CLI testing interface
    import argparse

    parser = argparse.ArgumentParser(description='Bulk sync testing')
    parser.add_argument('--dry-run', action='store_true', help='Plan only')
    parser.add_argument('--workers', type=int, default=4, help='Max parallel workers')
    parser.add_argument('--detailed', action='store_true', help='Show detailed results')
    parser.add_argument('--projects', nargs='+', help='Specific project keys to sync')

    args = parser.parse_args()

    try:
        engine = BulkSyncEngine(max_workers=args.workers, dry_run=args.dry_run)

        if args.projects:
            result = engine.sync_selective(args.projects)
        else:
            result = engine.sync_all()

        print(format_bulk_result(result, detailed=args.detailed))
        sys.exit(0 if result.failed_projects == 0 else 1)

    except Exception as e:
        print(f"✗ Bulk sync failed: {e}", file=sys.stderr)
        sys.exit(1)
