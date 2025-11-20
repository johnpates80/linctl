#!/usr/bin/env python3
"""
Selective sync module for BMAD sync operations.

Provides interactive selection and filtering capabilities.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Callable, Set

from sync_engine import SyncOperation


@dataclass
class SelectionFilter:
    """Filter criteria for selective sync."""
    epic: Optional[str] = None  # Filter by epic (e.g., "epic-1", "1")
    content_type: Optional[str] = None  # 'story' | 'epic' | 'sprint-status'
    status: Optional[str] = None  # BMAD status filter
    action: Optional[str] = None  # 'create' | 'update'
    risk_level: Optional[str] = None  # 'low' | 'medium' | 'high'


class SelectiveSync:
    """Interactive selection and filtering for sync operations."""

    def __init__(self, operations: List[SyncOperation]):
        """
        Initialize selective sync.

        Args:
            operations: List of sync operations
        """
        self.operations = operations
        self.selected: Set[int] = set(range(len(operations)))  # All selected by default

    def apply_filter(self, filter_criteria: SelectionFilter) -> List[int]:
        """
        Apply filter criteria and return matching operation indices.

        Args:
            filter_criteria: Filter criteria to apply

        Returns:
            List of operation indices that match the filter
        """
        matches = []

        for idx, op in enumerate(self.operations):
            if self._matches_filter(op, filter_criteria):
                matches.append(idx)

        return matches

    def _matches_filter(self, op: SyncOperation, criteria: SelectionFilter) -> bool:
        """Check if an operation matches filter criteria."""
        # Epic filter
        if criteria.epic:
            epic_num = criteria.epic.replace('epic-', '')
            if not op.content_key.startswith(f"{epic_num}-") and \
               not op.content_key == f"epic-{epic_num}":
                return False

        # Content type filter
        if criteria.content_type and op.content_type != criteria.content_type:
            return False

        # Status filter
        if criteria.status and op.state != criteria.status:
            return False

        # Action filter
        if criteria.action and op.action != criteria.action:
            return False

        return True

    def select_all(self):
        """Select all operations."""
        self.selected = set(range(len(self.operations)))

    def deselect_all(self):
        """Deselect all operations."""
        self.selected = set()

    def toggle_selection(self, idx: int):
        """Toggle selection for an operation."""
        if idx in self.selected:
            self.selected.remove(idx)
        else:
            self.selected.add(idx)

    def select_by_filter(self, criteria: SelectionFilter):
        """Select operations matching filter criteria."""
        matches = self.apply_filter(criteria)
        self.selected.update(matches)

    def deselect_by_filter(self, criteria: SelectionFilter):
        """Deselect operations matching filter criteria."""
        matches = self.apply_filter(criteria)
        self.selected.difference_update(matches)

    def get_selected_operations(self) -> List[SyncOperation]:
        """Get list of selected operations."""
        return [op for idx, op in enumerate(self.operations) if idx in self.selected]

    def get_selection_summary(self) -> Dict[str, Any]:
        """Get summary of current selection."""
        selected_ops = self.get_selected_operations()

        return {
            "total": len(self.operations),
            "selected": len(selected_ops),
            "create": sum(1 for op in selected_ops if op.action == "create"),
            "update": sum(1 for op in selected_ops if op.action == "update"),
            "by_type": self._count_by_type(selected_ops),
            "by_epic": self._count_by_epic(selected_ops)
        }

    def _count_by_type(self, operations: List[SyncOperation]) -> Dict[str, int]:
        """Count operations by content type."""
        counts = {}
        for op in operations:
            counts[op.content_type] = counts.get(op.content_type, 0) + 1
        return counts

    def _count_by_epic(self, operations: List[SyncOperation]) -> Dict[str, int]:
        """Count operations by epic."""
        counts = {}
        for op in operations:
            # Extract epic number from content key
            if op.content_type == 'story' and '-' in op.content_key:
                epic_num = op.content_key.split('-')[0]
                epic_key = f"epic-{epic_num}"
                counts[epic_key] = counts.get(epic_key, 0) + 1
            elif op.content_type == 'epic':
                counts[op.content_key] = counts.get(op.content_key, 0) + 1

        return counts

    def interactive_selection(self, colored: bool = True) -> List[SyncOperation]:
        """
        Run interactive selection mode.

        Args:
            colored: Use ANSI colors

        Returns:
            List of selected operations after user interaction
        """
        # Import color codes
        if colored:
            GREEN = '\033[92m'
            YELLOW = '\033[93m'
            RED = '\033[91m'
            BLUE = '\033[94m'
            BOLD = '\033[1m'
            RESET = '\033[0m'
            DIM = '\033[2m'
        else:
            GREEN = YELLOW = RED = BLUE = BOLD = RESET = DIM = ''

        while True:
            # Clear screen
            print('\033[2J\033[H' if colored else '\n' * 2)

            # Display header
            print(f"{BOLD}=== SELECTIVE SYNC ==={RESET}")
            print()

            # Display summary
            summary = self.get_selection_summary()
            print(f"Total operations: {summary['total']}")
            print(f"{GREEN}Selected: {summary['selected']}{RESET}")
            print(f"  Create: {summary['create']}, Update: {summary['update']}")
            print()

            # Display operations
            print(f"{BOLD}Operations:{RESET}")
            for idx, op in enumerate(self.operations):
                selected = idx in self.selected
                check = f"{GREEN}[✓]{RESET}" if selected else f"{DIM}[ ]{RESET}"
                op_type = f"{BLUE}{op.content_type}{RESET}"
                action = f"{YELLOW}{op.action}{RESET}"
                print(f"{idx + 1}. {check} {op_type} {op.content_key} ({action})")

            print()

            # Display menu
            print(f"{BOLD}Commands:{RESET}")
            print("  [a]   Select all")
            print("  [n]   Deselect all")
            print("  [NUM] Toggle operation (e.g., '1', '3')")
            print("  [f]   Filter by criteria")
            print("  [p]   Preview selected")
            print("  [c]   Continue with selection")
            print("  [q]   Quit/cancel")
            print()

            # Get user input
            try:
                choice = input(f"{BOLD}>{RESET} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return []

            # Process choice
            if choice == 'a':
                self.select_all()
            elif choice == 'n':
                self.deselect_all()
            elif choice == 'f':
                self._interactive_filter()
            elif choice == 'p':
                self._preview_selected(colored)
            elif choice == 'c':
                return self.get_selected_operations()
            elif choice == 'q':
                print("Cancelled.")
                return []
            elif choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(self.operations):
                    self.toggle_selection(idx)
                else:
                    print(f"{RED}Invalid operation number.{RESET}")
                    input("Press Enter to continue...")

    def _interactive_filter(self):
        """Interactive filter setup."""
        print("\nFilter by:")
        print("  1. Epic (e.g., 'epic-1' or '1')")
        print("  2. Content type (story, epic, sprint-status)")
        print("  3. Action (create, update)")
        print("  4. Cancel")
        print()

        try:
            choice = input("Choice: ").strip()
        except (EOFError, KeyboardInterrupt):
            return

        filter_criteria = SelectionFilter()

        if choice == '1':
            epic = input("Epic (e.g., '1' or 'epic-1'): ").strip()
            if epic:
                filter_criteria.epic = epic
        elif choice == '2':
            content_type = input("Content type (story/epic/sprint-status): ").strip()
            if content_type:
                filter_criteria.content_type = content_type
        elif choice == '3':
            action = input("Action (create/update): ").strip()
            if action:
                filter_criteria.action = action
        else:
            return

        # Ask whether to select or deselect
        mode = input("(s)elect or (d)eselect matching? [s/d]: ").strip().lower()

        if mode == 's':
            self.select_by_filter(filter_criteria)
        elif mode == 'd':
            self.deselect_by_filter(filter_criteria)

    def _preview_selected(self, colored: bool):
        """Preview selected operations."""
        selected_ops = self.get_selected_operations()

        print("\n" + "=" * 60)
        print("PREVIEW OF SELECTED OPERATIONS")
        print("=" * 60)
        print()

        for op in selected_ops:
            print(f"  • {op.content_type} {op.content_key} [{op.action}]")
            if op.title:
                print(f"    Title: {op.title}")

        print()
        input("Press Enter to continue...")


def select_operations_interactively(operations: List[SyncOperation],
                                   colored: bool = True) -> List[SyncOperation]:
    """
    Interactively select operations for sync (convenience function).

    Args:
        operations: List of operations to select from
        colored: Use ANSI colors

    Returns:
        List of selected operations
    """
    selector = SelectiveSync(operations)
    return selector.interactive_selection(colored=colored)
