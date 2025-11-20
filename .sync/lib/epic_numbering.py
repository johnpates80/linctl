#!/usr/bin/env python3
"""
Epic numbering system for BMAD ↔ Linear synchronization.

Manages RAE-XXX issue number allocation for epics with block-based reservation:
- Epic 1: RAE-360 to RAE-379 (20 numbers)
- Epic 2: RAE-380 to RAE-399 (20 numbers)
- Epic 3: RAE-400 to RAE-419 (20 numbers)
- Epic 4: RAE-420 to RAE-439 (20 numbers)
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class EpicNumberRange:
    """Represents a reserved number range for an epic."""

    epic_number: int
    base_number: int
    range_start: int
    range_end: int
    reserved_count: int = 20

    @property
    def available_numbers(self) -> List[int]:
        """Get list of all numbers in this range."""
        return list(range(self.range_start, self.range_end + 1))

    def contains(self, number: int) -> bool:
        """Check if a number falls within this range."""
        return self.range_start <= number <= self.range_end


class EpicNumberingSystem:
    """
    Manages epic number allocation and conflict detection.

    Configuration:
        - epic_base: Starting number for first epic (default: 360)
        - block_size: Numbers reserved per epic (default: 20)
        - registry_path: Path to number registry JSON
    """

    def __init__(
        self,
        epic_base: int = 360,
        block_size: int = 20,
        registry_path: Optional[Path] = None
    ):
        """
        Initialize numbering system.

        Args:
            epic_base: Base number for first epic (e.g., 360)
            block_size: Number of issues reserved per epic (e.g., 20)
            registry_path: Path to registry file (default: .sync/state/number_registry.json)
        """
        self.epic_base = epic_base
        self.block_size = block_size

        if registry_path is None:
            registry_path = Path('.sync/state/number_registry.json')
        self.registry_path = Path(registry_path)

        self._registry: Dict[str, Any] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        """Load existing registry from disk or create new one."""
        if self.registry_path.exists():
            try:
                self._registry = json.loads(
                    self.registry_path.read_text(encoding='utf-8')
                )
            except (json.JSONDecodeError, IOError):
                # Corrupted registry - start fresh
                self._registry = self._create_empty_registry()
        else:
            self._registry = self._create_empty_registry()

    def _create_empty_registry(self) -> Dict[str, Any]:
        """Create new empty registry structure."""
        return {
            "version": "1.0",
            "epic_base": self.epic_base,
            "block_size": self.block_size,
            "epics": {},
            "reserved_ranges": [],
            "created": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def _save_registry(self) -> None:
        """Atomically save registry to disk."""
        self._registry["last_updated"] = datetime.now(timezone.utc).isoformat()

        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write via temp file
        tmp = self.registry_path.with_suffix('.tmp')
        tmp.write_text(
            json.dumps(self._registry, indent=2, sort_keys=True),
            encoding='utf-8'
        )
        tmp.replace(self.registry_path)

    def calculate_epic_range(self, epic_number: int) -> EpicNumberRange:
        """
        Calculate number range for an epic.

        Args:
            epic_number: Epic number (1, 2, 3, 4, ...)

        Returns:
            EpicNumberRange with base and range boundaries

        Example:
            Epic 1: base=360, range=[360, 379]
            Epic 2: base=380, range=[380, 399]
        """
        base = self.epic_base + ((epic_number - 1) * self.block_size)
        return EpicNumberRange(
            epic_number=epic_number,
            base_number=base,
            range_start=base,
            range_end=base + self.block_size - 1,
            reserved_count=self.block_size
        )

    def reserve_epic_range(self, epic_number: int) -> EpicNumberRange:
        """
        Reserve number range for an epic.

        Args:
            epic_number: Epic number to reserve

        Returns:
            Reserved EpicNumberRange

        Raises:
            ValueError: If range conflicts with existing reservations
        """
        epic_range = self.calculate_epic_range(epic_number)

        # Check for conflicts
        conflicts = self.check_conflicts(epic_range)
        if conflicts:
            conflict_str = ", ".join(
                f"Epic {c['epic']} ({c['range'][0]}-{c['range'][1]})"
                for c in conflicts
            )
            raise ValueError(
                f"Epic {epic_number} range {epic_range.range_start}-{epic_range.range_end} "
                f"conflicts with: {conflict_str}"
            )

        # Ensure registry structure exists
        if "epics" not in self._registry:
            self._registry["epics"] = {}
        if "reserved_ranges" not in self._registry:
            self._registry["reserved_ranges"] = []

        # Register the range
        epic_key = str(epic_number)
        self._registry["epics"][epic_key] = {
            "epic_number": epic_number,
            "base": epic_range.base_number,
            "range": [epic_range.range_start, epic_range.range_end],
            "reserved_count": epic_range.reserved_count,
            "reserved_at": datetime.now(timezone.utc).isoformat(),
        }

        # Update reserved_ranges list
        self._registry["reserved_ranges"] = [
            meta["range"] for meta in self._registry["epics"].values()
        ]

        self._save_registry()
        return epic_range

    def check_conflicts(self, epic_range: EpicNumberRange) -> List[Dict[str, Any]]:
        """
        Check if epic range conflicts with existing reservations.

        Args:
            epic_range: Range to check

        Returns:
            List of conflicting epic registrations
        """
        conflicts = []

        for epic_key, meta in self._registry.get("epics", {}).items():
            existing_start, existing_end = meta["range"]

            # Skip self (same epic number)
            if meta["epic_number"] == epic_range.epic_number:
                continue

            # Check for overlap
            if (epic_range.range_start <= existing_end and
                epic_range.range_end >= existing_start):
                conflicts.append({
                    "epic": meta["epic_number"],
                    "range": meta["range"],
                    "base": meta["base"],
                })

        return conflicts

    def get_epic_range(self, epic_number: int) -> Optional[EpicNumberRange]:
        """
        Get reserved range for an epic.

        Args:
            epic_number: Epic number

        Returns:
            EpicNumberRange if reserved, None otherwise
        """
        epic_key = str(epic_number)
        meta = self._registry.get("epics", {}).get(epic_key)

        if not meta:
            return None

        return EpicNumberRange(
            epic_number=meta["epic_number"],
            base_number=meta["base"],
            range_start=meta["range"][0],
            range_end=meta["range"][1],
            reserved_count=meta["reserved_count"]
        )

    def is_epic_number_available(self, number: int) -> Tuple[bool, Optional[int]]:
        """
        Check if a specific issue number is available.

        Args:
            number: Issue number to check

        Returns:
            Tuple of (is_available, conflicting_epic_number)
        """
        for epic_key, meta in self._registry.get("epics", {}).items():
            start, end = meta["range"]
            if start <= number <= end:
                return False, meta["epic_number"]

        return True, None

    def list_all_ranges(self) -> List[EpicNumberRange]:
        """
        List all reserved epic ranges.

        Returns:
            List of EpicNumberRange objects, sorted by epic number
        """
        ranges = []
        for meta in sorted(
            self._registry.get("epics", {}).values(),
            key=lambda m: m["epic_number"]
        ):
            ranges.append(
                EpicNumberRange(
                    epic_number=meta["epic_number"],
                    base_number=meta["base"],
                    range_start=meta["range"][0],
                    range_end=meta["range"][1],
                    reserved_count=meta["reserved_count"]
                )
            )
        return ranges

    def get_registry_stats(self) -> Dict[str, Any]:
        """
        Get statistics about current registry.

        Returns:
            Dictionary with registry statistics
        """
        epics = self._registry.get("epics", {})

        total_reserved = sum(
            meta["reserved_count"] for meta in epics.values()
        )

        return {
            "epic_count": len(epics),
            "total_reserved_numbers": total_reserved,
            "epic_base": self.epic_base,
            "block_size": self.block_size,
            "registry_path": str(self.registry_path),
            "last_updated": self._registry.get("last_updated"),
        }


# Global numbering system instance
_numbering_system: Optional[EpicNumberingSystem] = None


def get_numbering_system(
    epic_base: int = 360,
    block_size: int = 20,
    registry_path: Optional[Path] = None
) -> EpicNumberingSystem:
    """
    Get or create global numbering system instance.

    Args:
        epic_base: Base number for first epic
        block_size: Numbers reserved per epic
        registry_path: Path to registry file

    Returns:
        EpicNumberingSystem instance
    """
    global _numbering_system

    if _numbering_system is None:
        _numbering_system = EpicNumberingSystem(
            epic_base=epic_base,
            block_size=block_size,
            registry_path=registry_path
        )

    return _numbering_system


if __name__ == '__main__':
    # Test the numbering system
    import sys

    system = get_numbering_system()

    print("Epic Numbering System - Test")
    print("=" * 50)

    # Test range calculation
    for epic_num in [1, 2, 3, 4]:
        epic_range = system.calculate_epic_range(epic_num)
        print(f"\nEpic {epic_num}:")
        print(f"  Base: RAE-{epic_range.base_number}")
        print(f"  Range: RAE-{epic_range.range_start} to RAE-{epic_range.range_end}")
        print(f"  Count: {epic_range.reserved_count} numbers")

    print("\n" + "=" * 50)
    print(f"Registry path: {system.registry_path}")

    # Try reserving epic 1
    try:
        print("\nReserving Epic 1...")
        range1 = system.reserve_epic_range(1)
        print(f"✓ Reserved RAE-{range1.range_start} to RAE-{range1.range_end}")
    except ValueError as e:
        print(f"✗ {e}")

    # Show stats
    stats = system.get_registry_stats()
    print(f"\nRegistry Stats:")
    print(f"  Epics: {stats['epic_count']}")
    print(f"  Total reserved: {stats['total_reserved_numbers']} numbers")
