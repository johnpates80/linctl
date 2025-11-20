#!/usr/bin/env python3
"""
Dry-run reporting module for BMAD sync operations.

Provides detailed simulation reports without making actual changes.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Any, List, Optional
import json

from sync_engine import SyncOperation


@dataclass
class DryRunResult:
    """Result of a dry-run simulation."""
    operation: SyncOperation
    would_succeed: bool
    estimated_duration_ms: int
    api_calls: List[Dict[str, Any]]  # List of API calls that would be made
    warnings: List[str]  # Potential issues


class DryRunSimulator:
    """Simulates sync operations and generates detailed reports."""

    def __init__(self):
        """Initialize dry-run simulator."""
        pass

    def simulate_operations(self, operations: List[SyncOperation]) -> List[DryRunResult]:
        """
        Simulate sync operations and return results.

        Args:
            operations: List of operations to simulate

        Returns:
            List of dry-run results
        """
        results = []

        for op in operations:
            result = self._simulate_operation(op)
            results.append(result)

        return results

    def _simulate_operation(self, op: SyncOperation) -> DryRunResult:
        """Simulate a single operation."""
        api_calls = []
        warnings = []

        # Determine API calls based on operation
        if op.action == "create":
            api_calls.append({
                "method": "POST",
                "endpoint": f"/issues",
                "payload": {
                    "title": op.title or "Untitled",
                    "teamId": op.team,
                    "projectId": op.project,
                    "stateId": op.state
                }
            })
            estimated_duration = 500  # ms
        elif op.action == "update":
            if not op.issue_id:
                warnings.append("No issue_id found - cannot update")
                api_calls.append({
                    "method": "PATCH",
                    "endpoint": f"/issues/{op.issue_id or 'UNKNOWN'}",
                    "payload": {
                        "title": op.title,
                        "stateId": op.state
                    }
                })
            else:
                api_calls.append({
                    "method": "PATCH",
                    "endpoint": f"/issues/{op.issue_id}",
                    "payload": {
                        "title": op.title,
                        "stateId": op.state
                    }
                })
            estimated_duration = 400  # ms
        else:
            warnings.append(f"Unknown action: {op.action}")
            estimated_duration = 0

        # Additional warnings
        if not op.title:
            warnings.append("No title specified")
        if not op.team:
            warnings.append("No team specified")

        # Determine success likelihood
        would_succeed = len(warnings) == 0

        return DryRunResult(
            operation=op,
            would_succeed=would_succeed,
            estimated_duration_ms=estimated_duration,
            api_calls=api_calls,
            warnings=warnings
        )

    def generate_report(self, results: List[DryRunResult],
                       format: str = "text") -> str:
        """
        Generate detailed dry-run report.

        Args:
            results: List of dry-run results
            format: Report format ('text' or 'json')

        Returns:
            Formatted report
        """
        if format == "json":
            return self._generate_json_report(results)
        else:
            return self._generate_text_report(results)

    def _generate_text_report(self, results: List[DryRunResult]) -> str:
        """Generate text-format report."""
        lines = []

        # Header
        lines.append("=" * 70)
        lines.append("DRY-RUN SIMULATION REPORT")
        lines.append("=" * 70)
        lines.append("")

        # Summary
        total = len(results)
        would_succeed = sum(1 for r in results if r.would_succeed)
        would_fail = total - would_succeed
        total_duration_ms = sum(r.estimated_duration_ms for r in results)
        total_duration_sec = total_duration_ms / 1000
        total_api_calls = sum(len(r.api_calls) for r in results)

        lines.append("SUMMARY:")
        lines.append(f"  Total Operations: {total}")
        lines.append(f"  Would Succeed: {would_succeed}")
        lines.append(f"  Would Fail: {would_fail}")
        lines.append(f"  Estimated Duration: {total_duration_sec:.2f}s")
        lines.append(f"  Total API Calls: {total_api_calls}")
        lines.append("")

        # Operations
        lines.append("OPERATIONS:")
        lines.append("")

        for idx, result in enumerate(results, 1):
            op = result.operation
            status_icon = "✓" if result.would_succeed else "✗"

            lines.append(f"{idx}. [{status_icon}] {op.action.upper()} {op.content_type} {op.content_key}")
            lines.append(f"   Title: {op.title or '(none)'}")
            lines.append(f"   Duration: {result.estimated_duration_ms}ms")

            # API calls
            if result.api_calls:
                lines.append(f"   API Calls:")
                for call in result.api_calls:
                    lines.append(f"     • {call['method']} {call['endpoint']}")

            # Warnings
            if result.warnings:
                lines.append(f"   Warnings:")
                for warning in result.warnings:
                    lines.append(f"     ⚠ {warning}")

            lines.append("")

        # Footer
        lines.append("=" * 70)
        lines.append("NOTE: This is a simulation. No changes have been made.")
        lines.append("=" * 70)

        return "\n".join(lines)

    def _generate_json_report(self, results: List[DryRunResult]) -> str:
        """Generate JSON-format report."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": len(results),
                "would_succeed": sum(1 for r in results if r.would_succeed),
                "would_fail": sum(1 for r in results if not r.would_succeed),
                "estimated_duration_ms": sum(r.estimated_duration_ms for r in results),
                "total_api_calls": sum(len(r.api_calls) for r in results)
            },
            "operations": [
                {
                    "operation": {
                        "action": r.operation.action,
                        "content_key": r.operation.content_key,
                        "content_type": r.operation.content_type,
                        "title": r.operation.title,
                        "issue_id": r.operation.issue_id
                    },
                    "would_succeed": r.would_succeed,
                    "estimated_duration_ms": r.estimated_duration_ms,
                    "api_calls": r.api_calls,
                    "warnings": r.warnings
                }
                for r in results
            ]
        }

        return json.dumps(report, indent=2)


def simulate_dry_run(operations: List[SyncOperation],
                    format: str = "text") -> str:
    """
    Simulate operations and generate report (convenience function).

    Args:
        operations: List of operations to simulate
        format: Report format ('text' or 'json')

    Returns:
        Formatted dry-run report
    """
    simulator = DryRunSimulator()
    results = simulator.simulate_operations(operations)
    return simulator.generate_report(results, format=format)
